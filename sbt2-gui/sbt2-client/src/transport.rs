use std::sync::Once;

use futures_util::{SinkExt, StreamExt};
use prost::Message as _;
use tokio::net::TcpStream;
use tokio_tungstenite::{
    MaybeTlsStream, WebSocketStream, connect_async_with_config,
    tungstenite::{
        self, Message,
        client::ClientRequestBuilder,
        http::{StatusCode, Uri},
        protocol::WebSocketConfig,
    },
};

use crate::{
    ClientError, ServerAddress, Token,
    protocol::{ClientMessage, ServerMessage},
};

pub(crate) const SUBPROTOCOL: &str = "sbt2.v1";
/// The protocol's limit for one serialized envelope.
pub(crate) const MAX_ENVELOPE: usize = 1_048_576;

type Socket = WebSocketStream<MaybeTlsStream<TcpStream>>;

/// One open WebSocket connection, speaking whole protocol envelopes.
pub(crate) struct Link(Socket);

impl Link {
    pub(crate) async fn open(address: &ServerAddress, token: &Token) -> Result<Self, ClientError> {
        install_crypto_provider();
        let request = request(address, token)?;
        let config = WebSocketConfig::default()
            .max_message_size(Some(MAX_ENVELOPE))
            .max_frame_size(Some(MAX_ENVELOPE));
        let (socket, _) = connect_async_with_config(request, Some(config), false)
            .await
            .map_err(open_error)?;
        Ok(Self(socket))
    }

    pub(crate) async fn send(&mut self, message: &ClientMessage) -> Result<(), ClientError> {
        let frame = Message::binary(message.encode_to_vec());
        self.0.send(frame).await.map_err(read_error)
    }

    /// The next server message; `Disconnected` once the server closes.
    pub(crate) async fn receive(&mut self) -> Result<ServerMessage, ClientError> {
        loop {
            match self.0.next().await {
                Some(Ok(Message::Binary(frame))) => return decode(&frame),
                Some(Ok(Message::Text(_))) => {
                    return Err(ClientError::Protocol("a text frame".to_owned()));
                }
                Some(Ok(Message::Close(_))) | None => return Err(ClientError::Disconnected),
                Some(Ok(_)) => {}
                Some(Err(error)) => return Err(read_error(error)),
            }
        }
    }
}

fn request(address: &ServerAddress, token: &Token) -> Result<ClientRequestBuilder, ClientError> {
    let uri: Uri = address
        .to_string()
        .parse()
        .map_err(|_| ClientError::InvalidAddress(address.to_string()))?;
    Ok(ClientRequestBuilder::new(uri)
        .with_sub_protocol(SUBPROTOCOL)
        .with_header("Authorization", format!("Bearer {}", token.expose())))
}

fn decode(frame: &[u8]) -> Result<ServerMessage, ClientError> {
    ServerMessage::decode(frame)
        .map_err(|error| ClientError::Protocol(format!("undecodable frame: {error}")))
}

fn open_error(error: tungstenite::Error) -> ClientError {
    match error {
        tungstenite::Error::Http(response) if response.status() == StatusCode::UNAUTHORIZED => {
            ClientError::Unauthorized
        }
        other => read_error(other),
    }
}

fn read_error(error: tungstenite::Error) -> ClientError {
    match error {
        tungstenite::Error::Capacity(error) => ClientError::Protocol(error.to_string()),
        tungstenite::Error::Protocol(error) => ClientError::Protocol(error.to_string()),
        tungstenite::Error::ConnectionClosed | tungstenite::Error::AlreadyClosed => {
            ClientError::Disconnected
        }
        other => ClientError::Transport(other.to_string()),
    }
}

// rustls has no default provider here, and wss:// needs one.
fn install_crypto_provider() {
    static INSTALL: Once = Once::new();
    INSTALL.call_once(|| {
        let _ = rustls::crypto::ring::default_provider().install_default();
    });
}
