//! The client of the sbt2 server.

pub mod protocol {
    //! The generated protocol messages.
    include!(concat!(env!("OUT_DIR"), "/protocol.rs"));
}
