//! The client of the sbt2 server.

mod address;
mod backoff;
mod connection;
mod dispatch;
mod error;
mod ids;
mod results;
mod session;
mod transport;
#[cfg(test)]
#[path = "version.rs"]
mod version_format;

pub use address::{ServerAddress, Token};
pub use backoff::Backoff;
pub use error::ClientError;
pub use results::RunMetrics;
pub use session::{Client, ConnectionState, Session, Subscription};

/// The version stamped at build time: the release tag, in the format of the Python packages.
pub const VERSION: &str = env!("SBT2_VERSION_STAMP");

mod generated {
    include!(concat!(env!("OUT_DIR"), "/protocol.rs"));
}

pub mod protocol {
    //! The generated protocol messages of `sbt2.protocol.v1`.
    pub use crate::generated::sbt2::protocol::v1::*;
}
