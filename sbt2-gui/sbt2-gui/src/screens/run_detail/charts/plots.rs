//! Builds the plots of the charts with `iced_plot`.

use iced::keyboard;
use iced_plot::{
    AxisLink, Color, LineStyle, MarkerStyle, MarkerType, PlotControls, PlotRenderStrategy,
    PlotWidget, PlotWidgetBuilder, Series,
};
use sbt2_client::Point;

use super::ticks::{date_label, date_ticks, integer_ticks, month_label, ticks};
use crate::{format, screens::section::Section};

const MAX_DRAWN: usize = 4_000;
pub(super) const STRATEGY: Color = Color::from_rgb(0.25, 0.55, 0.95);
pub(super) const BENCHMARK: Color = Color::from_rgb(0.95, 0.6, 0.2);
pub(super) const GAIN: Color = Color::from_rgb(0.15, 0.7, 0.35);
pub(super) const LOSS: Color = Color::from_rgb(0.85, 0.25, 0.25);
pub(super) const NEUTRAL: Color = Color::from_rgb(0.3, 0.3, 0.3);

pub(super) fn plot(
    data: &Section<Vec<Point>>,
    make: impl FnOnce(&[Point]) -> Result<PlotWidget, String>,
) -> Section<PlotWidget> {
    match data {
        Section::Loading => Section::Loading,
        Section::Failed(error) => Section::Failed(error.clone()),
        Section::Ready(points) if points.iter().all(|point| point.value.is_nan()) => {
            Section::Failed("No data".to_owned())
        }
        Section::Ready(points) => match make(points) {
            Ok(plot) => Section::Ready(plot),
            Err(error) => Section::Failed(error),
        },
    }
}

pub(super) struct Line<'a> {
    label: &'static str,
    color: Color,
    points: &'a [Point],
}

impl<'a> Line<'a> {
    pub(super) fn new(label: &'static str, color: Color, points: &'a [Point]) -> Self {
        Self {
            label,
            color,
            points,
        }
    }
}

pub(super) struct Axes {
    link: Option<AxisLink>,
    percent: bool,
}

impl Axes {
    pub(super) fn dates(link: Option<&AxisLink>, percent: bool) -> Self {
        Self {
            link: link.cloned(),
            percent,
        }
    }
}

fn builder() -> PlotWidgetBuilder {
    let mut controls = PlotControls::default();
    controls.unbind_scroll(keyboard::Modifiers::NONE);
    PlotWidgetBuilder::new()
        .with_render_strategy(PlotRenderStrategy::Canvas)
        .with_controls(controls)
}

pub(super) fn line_plot(lines: &[Line<'_>], axes: &Axes) -> Result<PlotWidget, String> {
    let mut plot = builder()
        .with_x_tick_producer(|min, max| ticks(date_ticks(min, max)))
        .with_x_tick_formatter(|tick| date_label(tick.value));
    if axes.percent {
        plot = plot.with_y_tick_formatter(|tick| format!("{:.1}%", tick.value * 100.0));
    }
    if let Some(link) = &axes.link {
        plot = plot.with_x_axis_link(link.clone());
    }
    for line in lines {
        for series in line_series(line) {
            plot = plot.add_series(series);
        }
    }
    finish(plot)
}

fn finish(plot: PlotWidgetBuilder) -> Result<PlotWidget, String> {
    plot.build()
        .map_err(|error| format!("Could not draw the chart: {error:?}"))
}

fn line_series(line: &Line<'_>) -> Vec<Series> {
    let mut labelled = false;
    let mut series = Vec::new();
    for segment in segments(line.points) {
        let segment = reduce(segment, MAX_DRAWN);
        let one = if segment.len() == 1 {
            Series::markers_only(segment, MarkerStyle::circle(3.0))
        } else {
            Series::line_only(segment, LineStyle::solid())
        };
        let one = one.with_color(line.color);
        series.push(if labelled {
            one
        } else {
            labelled = true;
            one.with_label(line.label)
        });
    }
    series
}

pub(super) fn heatmap(points: &[Point]) -> Result<PlotWidget, String> {
    let cells = monthly_grid(points);
    let scale = cells
        .iter()
        .map(|cell| cell.value.abs())
        .filter(|value| value.is_finite())
        .fold(f64::MIN_POSITIVE, f64::max);
    let positions = cells
        .iter()
        .map(|cell| [cell.month as f64, cell.year as f64])
        .collect();
    let colors = cells
        .iter()
        .map(|cell| heat_color(cell.value, scale))
        .collect();
    let first = cells.first().map_or(0, |cell| cell.year) as f64;
    let last = cells.last().map_or(0, |cell| cell.year) as f64;
    let squares = Series::markers_only(positions, MarkerStyle::new_world(0.9, MarkerType::Square))
        .with_point_colors(colors);
    let plot = builder()
        .with_x_lim(0.5, 12.5)
        .with_y_lim(first - 0.5, last + 0.5)
        .with_x_tick_producer(integer_ticks)
        .with_x_tick_formatter(|tick| month_label(tick.value))
        .with_y_tick_producer(integer_ticks)
        .with_y_tick_formatter(|tick| format!("{:.0}", tick.value))
        .add_series(squares);
    finish(plot)
}

pub(super) fn bars(points: &[Point]) -> Result<PlotWidget, String> {
    let mut plot = builder()
        .with_x_tick_producer(integer_ticks)
        .with_x_tick_formatter(|tick| format!("{:.0}", tick.value))
        .with_y_tick_formatter(|tick| format!("{:.1}%", tick.value * 100.0));
    for (year, value) in yearly_values(points) {
        let color = if value < 0.0 { LOSS } else { GAIN };
        let bar = Series::line_only(
            vec![[year as f64, 0.0], [year as f64, value]],
            LineStyle::solid(),
        )
        .line_width_world(0.6)
        .with_color(color);
        plot = plot.add_series(bar);
    }
    finish(plot)
}

fn heat_color(value: f64, scale: f64) -> Color {
    if value.is_nan() {
        return NEUTRAL;
    }
    let strength = (value.abs() / scale).clamp(0.0, 1.0) as f32;
    let target = if value < 0.0 { LOSS } else { GAIN };
    let mix = |from: f32, to: f32| from + (to - from) * strength;
    Color::from_rgb(
        mix(NEUTRAL.r, target.r),
        mix(NEUTRAL.g, target.g),
        mix(NEUTRAL.b, target.b),
    )
}

/// At most `limit` points: the lowest and the highest of each bucket, in time order.
pub(super) fn reduce(segment: Vec<[f64; 2]>, limit: usize) -> Vec<[f64; 2]> {
    if segment.len() <= limit {
        return segment;
    }
    let size = segment.len().div_ceil(limit / 2);
    let mut reduced = Vec::with_capacity(limit);
    for bucket in segment.chunks(size) {
        let lowest = (0..bucket.len()).min_by(|a, b| bucket[*a][1].total_cmp(&bucket[*b][1]));
        let highest = (0..bucket.len()).max_by(|a, b| bucket[*a][1].total_cmp(&bucket[*b][1]));
        let (Some(lowest), Some(highest)) = (lowest, highest) else {
            continue;
        };
        reduced.push(bucket[lowest.min(highest)]);
        if lowest != highest {
            reduced.push(bucket[lowest.max(highest)]);
        }
    }
    reduced
}

/// The points as runs of consecutive defined values, as `[seconds, value]`;
/// a NaN ends a run.
pub(super) fn segments(points: &[Point]) -> Vec<Vec<[f64; 2]>> {
    let mut segments: Vec<Vec<[f64; 2]>> = Vec::new();
    let mut broken = true;
    for point in points {
        if point.value.is_nan() {
            broken = true;
            continue;
        }
        let position = [point.ts as f64 / 1e9, point.value];
        match segments.last_mut() {
            Some(segment) if !broken => segment.push(position),
            _ => segments.push(vec![position]),
        }
        broken = false;
    }
    segments
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct MonthCell {
    pub(super) year: i64,
    pub(super) month: i64,
    pub(super) value: f64,
}

/// The monthly returns by the UTC year and month of their timestamps, oldest first.
pub(super) fn monthly_grid(points: &[Point]) -> Vec<MonthCell> {
    points
        .iter()
        .map(|point| {
            let (year, month, _) = format::civil(point.ts.div_euclid(1_000_000_000));
            MonthCell {
                year,
                month,
                value: point.value,
            }
        })
        .collect()
}

fn yearly_values(points: &[Point]) -> Vec<(i64, f64)> {
    points
        .iter()
        .filter(|point| !point.value.is_nan())
        .map(|point| {
            let (year, _, _) = format::civil(point.ts.div_euclid(1_000_000_000));
            (year, point.value)
        })
        .collect()
}
