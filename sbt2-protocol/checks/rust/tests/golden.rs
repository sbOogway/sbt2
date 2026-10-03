//! Every golden fixture decodes with prost to its textproto, and re-encodes to the same bytes.

use std::{fs, path::Path};

use sbt2_protocol_checks::check_fixture;

const HEADER: &str = "# proto-message: ";

fn textprotos(dir: &Path, found: &mut Vec<std::path::PathBuf>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            textprotos(&path, found);
        } else if path.extension().is_some_and(|ext| ext == "textproto") {
            found.push(path);
        }
    }
}

#[test]
fn fixtures_round_trip() {
    let golden = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../golden");
    let mut fixtures = Vec::new();
    textprotos(&golden, &mut fixtures);
    fixtures.sort();
    assert!(
        !fixtures.is_empty(),
        "no fixtures under {}",
        golden.display()
    );

    let failures: Vec<String> = fixtures
        .iter()
        .filter_map(|path| {
            let text = fs::read_to_string(path).unwrap();
            let binary = fs::read(path.with_extension("binpb")).unwrap();
            let result = match text
                .lines()
                .next()
                .and_then(|line| line.strip_prefix(HEADER))
            {
                Some(name) => check_fixture(name.trim(), &text, &binary),
                None => Err(format!("does not start with {HEADER:?}")),
            };
            result
                .err()
                .map(|err| format!("{}: {err}", path.strip_prefix(&golden).unwrap().display()))
        })
        .collect();
    assert!(failures.is_empty(), "\n{}", failures.join("\n"));
}
