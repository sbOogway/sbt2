//! An in-process fake of the sbt2 server on 127.0.0.1.

use std::{future::Future, sync::Arc};

use futures_util::{SinkExt, StreamExt};
use prost::Message as _;
use sbt2_client::{
    ServerAddress,
    protocol::{
        ClientMessage, RunList, RunSummary, ServerMessage, Welcome, client_message,
        server_message::Body,
    },
};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::{
    WebSocketStream, accept_hdr_async,
    tungstenite::{
        Message,
        handshake::server::{Callback, ErrorResponse, Request, Response},
        http::{HeaderValue, StatusCode},
    },
};

pub const TOKEN: &str = "s3cret-token";

/// One accepted connection.
pub struct Peer(WebSocketStream<TcpStream>);

impl Peer {
    pub async fn receive(&mut self) -> Option<ClientMessage> {
        loop {
            match self.0.next().await? {
                Ok(Message::Binary(frame)) => return Some(ClientMessage::decode(&*frame).unwrap()),
                Ok(Message::Close(_)) | Err(_) => return None,
                Ok(_) => {}
            }
        }
    }

    pub async fn send(&mut self, message: ServerMessage) {
        self.send_raw(message.encode_to_vec()).await;
    }

    pub async fn send_raw(&mut self, frame: Vec<u8>) {
        let _ = self.0.send(Message::binary(frame)).await;
    }

    /// Reads `Hello` and answers it.
    pub async fn greet(&mut self) -> ClientMessage {
        let hello = self.receive().await.expect("a Hello");
        assert!(matches!(hello.body, Some(client_message::Body::Hello(_))));
        self.send(welcome(hello.request_id)).await;
        hello
    }
}

pub fn welcome(request_id: u64) -> ServerMessage {
    reply(
        request_id,
        Body::Welcome(Welcome {
            server_version: "9.9.9".to_owned(),
            capabilities: vec![sbt2_client::protocol::Capability::Results.into()],
        }),
    )
}

pub fn reply(request_id: u64, body: Body) -> ServerMessage {
    ServerMessage {
        request_id,
        body: Some(body),
        ..ServerMessage::default()
    }
}

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

/// Serves each connection with `session`, which gets the connection's number from 0.
pub async fn serve<F, Fut>(session: F) -> ServerAddress
where
    F: Fn(usize, Peer) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = ()> + Send + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = format!("ws://{}", listener.local_addr().unwrap());
    let session = Arc::new(session);
    tokio::spawn(async move {
        for number in 0.. {
            let (stream, _) = listener.accept().await.unwrap();
            let session = Arc::clone(&session);
            tokio::spawn(async move {
                if let Ok(socket) = accept_hdr_async(stream, Admit).await {
                    session(number, Peer(socket)).await;
                }
            });
        }
    });
    ServerAddress::parse(&address).unwrap()
}

struct Admit;

impl Callback for Admit {
    fn on_request(
        self,
        request: &Request,
        mut response: Response,
    ) -> Result<Response, ErrorResponse> {
        let headers = request.headers();
        let bearer = format!("Bearer {TOKEN}");
        if headers
            .get("authorization")
            .and_then(|value| value.to_str().ok())
            != Some(&bearer)
        {
            return Err(refusal(StatusCode::UNAUTHORIZED, "Unauthorized"));
        }
        let offered = headers
            .get("sec-websocket-protocol")
            .and_then(|value| value.to_str().ok());
        if offered != Some("sbt2.v1") {
            return Err(refusal(StatusCode::BAD_REQUEST, "bad subprotocol"));
        }
        response.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_static("sbt2.v1"),
        );
        Ok(response)
    }
}

fn refusal(status: StatusCode, reason: &str) -> ErrorResponse {
    let mut response = ErrorResponse::new(Some(reason.to_owned()));
    *response.status_mut() = status;
    response
}
