//! The client of the sbt2 server.

mod error;
mod net;
mod results;
mod session;
#[cfg(test)]
#[path = "version.rs"]
mod version_format;

pub use error::ClientError;
pub use net::{Backoff, ServerAddress, Token};
pub use results::{Cell, Point, RunMetrics, Table};
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
