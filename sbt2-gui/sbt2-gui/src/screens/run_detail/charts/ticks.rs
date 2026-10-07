//! The ticks and labels of the chart axes.

use iced_plot::{Tick, TickWeight};

use crate::format;

const MONTHS: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
pub(super) fn date_label(seconds: f64) -> String {
    format::utc_day(seconds.floor() as i64)
}

/// Midnights of UTC days, spaced so that about eight or fewer fall in the range.
pub(super) fn date_ticks(min: f64, max: f64) -> Vec<f64> {
    const DAY: f64 = 86_400.0;
    const STEPS: [f64; 10] = [
        1.0, 2.0, 7.0, 14.0, 30.0, 91.0, 182.0, 365.0, 730.0, 1_825.0,
    ];
    let step = STEPS
        .into_iter()
        .map(|days| days * DAY)
        .find(|step| (max - min) / step <= 8.0)
        .unwrap_or(3_650.0 * DAY);
    let first = (min / step).ceil() as i64;
    let last = (max / step).floor() as i64;
    (first..=last).map(|index| index as f64 * step).collect()
}

pub(super) fn ticks(values: Vec<f64>) -> Vec<Tick> {
    let step = values.windows(2).map(|pair| pair[1] - pair[0]).next();
    values
        .into_iter()
        .map(|value| Tick::new(value, step.unwrap_or(1.0), TickWeight::Major))
        .collect()
}

pub(super) fn integer_ticks(min: f64, max: f64) -> Vec<Tick> {
    let values = (min.ceil() as i64..=max.floor() as i64).map(|value| value as f64);
    ticks(values.collect())
}

pub(super) fn month_label(month: f64) -> String {
    let index = month.round() as usize;
    MONTHS
        .get(index.wrapping_sub(1))
        .map_or_else(String::new, |name| (*name).to_owned())
}
