use std::time::Duration;

use sbt2_client::{Backoff, Client, ClientError, ConnectionState, Token, protocol::RunFilter};
use tokio::time::timeout;

use crate::runs::run_chunk;
use crate::support::{TOKEN, serve};

#[tokio::test]
async fn a_dropped_connection_fails_outstanding_requests_and_reconnects_with_hello() {
    let address = serve(|number, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        if number > 0 {
            peer.send(run_chunk(request.request_id, 0, true, &["after"]))
                .await;
            peer.receive().await;
        }
    })
    .await;
    let backoff = Backoff::new(Duration::from_millis(20), Duration::from_millis(80));
    let session = timeout(
        Duration::from_secs(5),
        Client::new(address, Token::new(TOKEN))
            .backoff(backoff)
            .connect(),
    )
    .await
    .unwrap()
    .unwrap();
    let mut states = session.states();
    assert_eq!(session.state(), ConnectionState::Connected);

    let dropped = session.list_runs(RunFilter::default()).await;

    assert_eq!(dropped.err(), Some(ClientError::Disconnected));
    let mut seen = Vec::new();
    while seen.last() != Some(&ConnectionState::Connected) {
        timeout(Duration::from_secs(5), states.changed())
            .await
            .unwrap()
            .unwrap();
        seen.push(*states.borrow_and_update());
    }
    assert_eq!(
        seen,
        [ConnectionState::Reconnecting, ConnectionState::Connected]
    );
    let runs = session.list_runs(RunFilter::default()).await.unwrap();
    assert_eq!(runs[0].run_id, "after");
}
