//! Generates the prost types from the protocol's .proto files, compiled by protox: no protoc.

use std::{env, fs, path::PathBuf};

fn main() {
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
