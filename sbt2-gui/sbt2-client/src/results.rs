//! The decoded results of a run.

use crate::protocol::Metric;

/// The metrics of a run, with the currency of its money values.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct RunMetrics {
    pub currency: String,
    pub entries: Vec<Metric>,
}
