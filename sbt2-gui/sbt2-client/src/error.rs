use crate::protocol::ErrorCode;

/// Why a client operation failed.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ClientError {
    #[error("not a ws:// or wss:// server address: {0}")]
    InvalidAddress(String),
    #[error("the server refused the token")]
    Unauthorized,
    #[error("the connection is down")]
    Disconnected,
    #[error("the server broke the protocol: {0}")]
    Protocol(String),
    #[error("transport error: {0}")]
    Transport(String),
    #[error("{code:?}: {message}")]
    Server { code: ErrorCode, message: String },
}
