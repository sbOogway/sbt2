//! The wire to the server: its address and token, the WebSocket link, and the
//! backoff between reconnects.

mod address;
mod backoff;
mod transport;

pub use address::{ServerAddress, Token};
pub use backoff::Backoff;
pub(crate) use transport::Link;
