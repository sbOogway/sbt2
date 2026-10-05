//! The decoded results of a run.

use crate::protocol::Metric;

/// One sample of a series: a UTC time and a value, NaN where it is undefined.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    /// Nanoseconds since the Unix epoch.
    pub ts: i64,
    pub value: f64,
}

/// One value of a `Table`.
#[derive(Debug, Clone, PartialEq)]
pub enum Cell {
    Null,
    Int(i64),
    Float(f64),
    Text(String),
    /// A UTC time, in nanoseconds since the Unix epoch.
    Time(i64),
    Bool(bool),
}

/// Rows of cells under named columns, as the server stored them.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Table {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Cell>>,
}

/// The metrics of a run, with the currency of its money values.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct RunMetrics {
    pub currency: String,
    pub entries: Vec<Metric>,
}
