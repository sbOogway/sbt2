//! A fake reply that lists runs.

use sbt2_client::protocol::{RunList, RunSummary, ServerMessage, server_message::Body};

use crate::support::reply;

pub fn run_chunk(request_id: u64, index: u64, last: bool, run_ids: &[&str]) -> ServerMessage {
    let runs = run_ids
        .iter()
        .map(|id| RunSummary {
            run_id: (*id).to_owned(),
            ..RunSummary::default()
        })
        .collect();
    reply(request_id, Body::RunList(RunList { index, last, runs }))
}
