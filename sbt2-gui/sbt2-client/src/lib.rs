//! The client of the sbt2 server.

mod address;
mod error;

pub use address::{ServerAddress, Token};
pub use error::ClientError;

mod generated {
    include!(concat!(env!("OUT_DIR"), "/protocol.rs"));
}

pub mod protocol {
    //! The generated protocol messages of `sbt2.protocol.v1`.
    pub use crate::generated::sbt2::protocol::v1::*;
}
