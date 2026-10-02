//! Generates the prost types from this repo's .proto files, and `check_fixture`, which
//! dispatches a fixture's message name to its type.

use std::{env, fmt::Write, fs, path::PathBuf};

use prost::Message;

fn main() {
    let root = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("../..");
    let protos: Vec<PathBuf> = fs::read_dir(root.join("sbt2/protocol/v1"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "proto"))
        .collect();
    for proto in &protos {
        println!("cargo:rerun-if-changed={}", proto.display());
    }
    println!(
        "cargo:rerun-if-changed={}",
        root.join("sbt2/protocol/v1").display()
    );

    let fds = protox::compile(&protos, [&root]).unwrap();
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    fs::write(out.join("descriptor.binpb"), fds.encode_to_vec()).unwrap();

    let mut dispatch = String::from(
        "pub fn check_fixture(name: &str, text: &str, binary: &[u8]) -> Result<(), String> {\n    match name {\n",
    );
    for file in fds
        .file
        .iter()
        .filter(|file| file.package() == "sbt2.protocol.v1")
    {
        for message in &file.message_type {
            let name = message.name();
            writeln!(
                dispatch,
                "        \"sbt2.protocol.v1.{name}\" => crate::check::<sbt2::protocol::v1::{name}>(name, text, binary),"
            )
            .unwrap();
        }
    }
    dispatch.push_str("        _ => Err(format!(\"{name} is not a top-level sbt2.protocol.v1 message\")),\n    }\n}\n");
    fs::write(out.join("dispatch.rs"), dispatch).unwrap();

    prost_build::Config::new()
        // deterministic, as buf convert is: map entries sorted by key
        .btree_map(["."])
        .include_file("protocol.rs")
        .compile_fds(fds)
        .unwrap();
}
