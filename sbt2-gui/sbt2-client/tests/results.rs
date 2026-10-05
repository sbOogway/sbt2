mod support;

use std::time::Duration;

use sbt2_client::{
    Client, ClientError, ServerAddress, Session, Token,
    protocol::{
        Error, ErrorCode, Metric, Metrics, RunSummary, ServerMessage, client_message,
        server_message::Body,
    },
};
use support::{TOKEN, reply, serve};
use tokio::time::timeout;

async fn connected(address: ServerAddress) -> Session {
    timeout(
        Duration::from_secs(5),
        Client::new(address, Token::new(TOKEN)).connect(),
    )
    .await
    .expect("connect timed out")
    .expect("connect failed")
}

fn metrics_chunk(request_id: u64, index: u64, last: bool, names: &[&str]) -> ServerMessage {
    let entries = names
        .iter()
        .map(|name| Metric {
            name: (*name).to_owned(),
            value: Some("1.5".to_owned()),
            ..Metric::default()
        })
        .collect();
    let currency = "USD".to_owned();
    let chunk = Metrics {
        index,
        last,
        currency,
        entries,
    };
    reply(request_id, Body::Metrics(chunk))
}

fn error_reply(request_id: u64, code: ErrorCode, message: &str) -> ServerMessage {
    let error = Error {
        code: code.into(),
        message: message.to_owned(),
        ..Error::default()
    };
    reply(request_id, Body::Error(error))
}

#[tokio::test]
async fn get_run_returns_the_run_summary() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        let Some(client_message::Body::GetRun(get)) = request.body else {
            panic!("not a GetRun");
        };
        assert_eq!(get.run_id, "r1");
        let summary = RunSummary {
            run_id: "r1".to_owned(),
            strategy: "ema".to_owned(),
            ..RunSummary::default()
        };
        let body = Body::RunSummary(Box::new(summary));
        peer.send(reply(request.request_id, body)).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let run = session.get_run("r1").await.unwrap();

    assert_eq!((run.run_id.as_str(), run.strategy.as_str()), ("r1", "ema"));
}

#[tokio::test]
async fn get_metrics_joins_the_entries_of_all_chunks() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        assert!(matches!(
            request.body,
            Some(client_message::Body::GetMetrics(_))
        ));
        let id = request.request_id;
        peer.send(metrics_chunk(id, 0, false, &["a", "b"])).await;
        peer.send(metrics_chunk(id, 1, true, &["c"])).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let metrics = session.get_metrics("r1").await.unwrap();

    let names: Vec<_> = metrics.entries.iter().map(|m| m.name.as_str()).collect();
    assert_eq!(metrics.currency, "USD");
    assert_eq!(names, ["a", "b", "c"]);
}

#[tokio::test]
async fn a_server_error_keeps_its_code_and_message() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        let error = error_reply(request.request_id, ErrorCode::NotFound, "no such run");
        peer.send(error).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let result = session.get_run("missing").await;

    assert_eq!(
        result.err(),
        Some(ClientError::Server {
            code: ErrorCode::NotFound,
            message: "no such run".to_owned(),
        })
    );
}
