use std::process::Command;

#[test]
fn the_version_flag_prints_the_version_and_exits() {
    let output = Command::new(env!("CARGO_BIN_EXE_sbt2-gui"))
        .arg("--version")
        .output()
        .unwrap();

    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        format!("{}\n", sbt2_client::VERSION)
    );
}
