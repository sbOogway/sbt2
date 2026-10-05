//! Generates the prost types from the protocol's .proto files, compiled by protox: no protoc.

use std::{env, fs, path::PathBuf, process::Command};

#[path = "src/version.rs"]
mod version;

fn main() {
    stamp_version();
    compile_protocol();
}

fn stamp_version() {
    println!("cargo:rerun-if-env-changed=SBT2_VERSION");
    for path in ["HEAD", "refs/tags", "packed-refs"] {
        if let Some(git_path) = git(&["rev-parse", "--git-path", path]) {
            println!("cargo:rerun-if-changed={git_path}");
        }
    }
    let describe = git(&["describe", "--tags", "--long", "--match", "v[0-9]*"]);
    let variable = env::var("SBT2_VERSION").ok();
    let version = version::stamp(variable.as_deref(), describe.as_deref());
    println!("cargo:rustc-env=SBT2_VERSION_STAMP={version}");
}

fn git(arguments: &[&str]) -> Option<String> {
    let output = Command::new("git").args(arguments).output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn compile_protocol() {
    let root = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("../../sbt2-protocol");
    let folder = root.join("sbt2/protocol/v1");
    let protos: Vec<PathBuf> = fs::read_dir(&folder)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "proto"))
        .collect();
    println!("cargo:rerun-if-changed={}", folder.display());
    for proto in &protos {
        println!("cargo:rerun-if-changed={}", proto.display());
    }
    let fds = protox::compile(&protos, [&root]).unwrap();
    prost_build::Config::new()
        .boxed(".sbt2.protocol.v1.ClientMessage.body.put_venue_profile")
        .boxed(".sbt2.protocol.v1.ClientMessage.body.submit_run")
        .boxed(".sbt2.protocol.v1.ServerMessage.body.run_summary")
        .include_file("protocol.rs")
        .compile_fds(fds)
        .unwrap();
}
