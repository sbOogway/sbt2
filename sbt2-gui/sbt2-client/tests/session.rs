mod support;

use std::time::Duration;

use sbt2_client::{
    Client, ClientError, ServerAddress, Token,
    protocol::{Capability, RunFilter, client_message},
};
use support::{TOKEN, run_chunk, serve};
use tokio::time::timeout;

async fn connected(address: ServerAddress) -> sbt2_client::Session {
    timeout(
        Duration::from_secs(5),
        Client::new(address, Token::new(TOKEN)).connect(),
    )
    .await
    .expect("connect timed out")
    .expect("connect failed")
}

#[tokio::test]
async fn connect_sends_the_token_and_subprotocol_then_hello_and_returns_welcome() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        peer.receive().await;
    })
    .await;

    let session = connected(address).await;

    let welcome = session.welcome();
    assert_eq!(welcome.server_version, "9.9.9");
    assert_eq!(welcome.capabilities, [Capability::Results as i32]);
}

#[tokio::test]
async fn the_hello_carries_the_stamped_version() {
    let (sent, mut received) = tokio::sync::mpsc::unbounded_channel();
    let address = serve(move |_, mut peer| {
        let sent = sent.clone();
        async move {
            let hello = peer.greet().await;
            let _ = sent.send(hello);
            peer.receive().await;
        }
    })
    .await;

    let _session = connected(address).await;

    let hello = received.recv().await.expect("a Hello");
    let Some(client_message::Body::Hello(hello)) = hello.body else {
        panic!("not a Hello");
    };
    assert_eq!(hello.client_version, sbt2_client::VERSION);
}

#[tokio::test]
async fn a_wrong_token_fails_the_connection_as_unauthorized() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
    })
    .await;

    let result = Client::new(address, Token::new("wrong")).connect().await;

    assert_eq!(result.err(), Some(ClientError::Unauthorized));
}

#[tokio::test]
async fn list_runs_returns_every_run_across_chunks() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        assert!(matches!(
            request.body,
            Some(client_message::Body::ListRuns(_))
        ));
        let id = request.request_id;
        peer.send(run_chunk(id, 0, false, &["a", "b"])).await;
        peer.send(run_chunk(id, 1, false, &["c"])).await;
        peer.send(run_chunk(id, 2, true, &[])).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let runs = session.list_runs(RunFilter::default()).await.unwrap();

    let ids: Vec<_> = runs.iter().map(|run| run.run_id.as_str()).collect();
    assert_eq!(ids, ["a", "b", "c"]);
}

#[tokio::test]
async fn concurrent_requests_each_get_their_own_reply() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let first = peer.receive().await.unwrap();
        let second = peer.receive().await.unwrap();
        for (request, tag) in [(second, "second"), (first, "first")] {
            peer.send(run_chunk(request.request_id, 0, false, &[tag]))
                .await;
        }
        for request_id in [2, 3] {
            peer.send(run_chunk(request_id, 1, true, &[])).await;
        }
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let (first, second) = tokio::join!(
        session.list_runs(RunFilter::default()),
        session.list_runs(RunFilter::default()),
    );

    let ids = |runs: Vec<sbt2_client::protocol::RunSummary>| -> Vec<String> {
        runs.into_iter().map(|run| run.run_id).collect()
    };
    let (first, second) = (ids(first.unwrap()), ids(second.unwrap()));
    assert_eq!(first, ["first"]);
    assert_eq!(second, ["second"]);
}

#[tokio::test]
async fn an_oversized_or_undecodable_frame_is_an_error_not_a_panic() {
    let garbage = vec![0xff; 16];
    let oversized = vec![0; 1_048_577];
    for frame in [garbage, oversized] {
        let address = serve(move |_, mut peer| {
            let frame = frame.clone();
            async move {
                peer.greet().await;
                peer.receive().await;
                peer.send_raw(frame).await;
                peer.receive().await;
            }
        })
        .await;
        let session = connected(address).await;

        let result = session.list_runs(RunFilter::default()).await;

        assert!(
            matches!(result, Err(ClientError::Protocol(_))),
            "{result:?}"
        );
    }
}
