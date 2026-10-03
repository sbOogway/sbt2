//! The golden fixtures' check for prost: see `tests/golden.rs`.

use std::sync::LazyLock;

use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};

include!(concat!(env!("OUT_DIR"), "/protocol.rs"));
include!(concat!(env!("OUT_DIR"), "/dispatch.rs"));

static POOL: LazyLock<DescriptorPool> = LazyLock::new(|| {
    DescriptorPool::decode(include_bytes!(concat!(env!("OUT_DIR"), "/descriptor.binpb")).as_slice())
        .unwrap()
});

/// Decodes `binary` as a `T`, compares it with the textproto `text`, and re-encodes it to
/// the same bytes.
fn check<T: Message + Default + PartialEq>(
    name: &str,
    text: &str,
    binary: &[u8],
) -> Result<(), String> {
    let decoded = T::decode(binary).map_err(|err| format!("the .binpb does not decode: {err}"))?;

    // prost has no text format: parse it dynamically, then go through the wire format
    let descriptor = POOL
        .get_message_by_name(name)
        .ok_or(format!("{name} is not in the pool"))?;
    let parsed = DynamicMessage::parse_text_format(descriptor, text)
        .map_err(|err| format!("the textproto does not parse: {err}"))?;
    let parsed = T::decode(parsed.encode_to_vec().as_slice()).unwrap();
    if decoded != parsed {
        return Err("the .binpb decodes to another message than the textproto".into());
    }

    if decoded.encode_to_vec() != binary {
        return Err("re-encoding the .binpb gives other bytes".into());
    }
    Ok(())
}
