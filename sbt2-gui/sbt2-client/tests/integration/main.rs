//! The integration tests, in one binary: each test binary links every dependency.

#[path = "../support/runs.rs"]
mod runs;
#[path = "../support/mod.rs"]
mod support;

mod reconnect;
mod results;
mod session;
