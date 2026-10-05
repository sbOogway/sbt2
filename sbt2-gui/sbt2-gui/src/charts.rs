//! The tearsheet charts of a run. The only module that uses `iced_plot`.

use iced::{
    Element, Length, keyboard,
    widget::{column, container, text},
};
use iced_plot::{
    AxisLink, Color, LineStyle, MarkerStyle, MarkerType, PlotControls, PlotRenderStrategy,
    PlotUiMessage, PlotWidget, PlotWidgetBuilder, Series, Tick, TickWeight,
};
use sbt2_client::Point;

use crate::{dates, section::Section};

const PLOT_HEIGHT: f32 = 300.0;
const MAX_DRAWN: usize = 4_000;
const MONTHS: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const STRATEGY: Color = Color::from_rgb(0.25, 0.55, 0.95);
const BENCHMARK: Color = Color::from_rgb(0.95, 0.6, 0.2);
const GAIN: Color = Color::from_rgb(0.15, 0.7, 0.35);
const LOSS: Color = Color::from_rgb(0.85, 0.25, 0.25);
const NEUTRAL: Color = Color::from_rgb(0.3, 0.3, 0.3);

/// The data sets of the charts; the benchmark has its own call in `Charts::set_benchmark`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Chart {
    Equity,
    Drawdown,
    Returns,
    RollingSharpe,
    Monthly,
    Yearly,
}

impl Chart {
    fn title(self) -> &'static str {
        match self {
            Self::Equity => "Equity",
            Self::Drawdown => "Drawdown",
            Self::Returns => "Daily returns",
            Self::RollingSharpe => "Rolling Sharpe (60 days)",
            Self::Monthly => "Monthly returns",
            Self::Yearly => "Yearly returns",
        }
    }
}

/// A message of one plot, such as a pan or a zoom.
#[derive(Debug, Clone)]
pub struct Message {
    chart: Chart,
    plot: PlotUiMessage,
}

#[derive(Default)]
struct Data {
    equity: Section<Vec<Point>>,
    drawdown: Section<Vec<Point>>,
    returns: Section<Vec<Point>>,
    benchmark: Section<Vec<Point>>,
    rolling_sharpe: Section<Vec<Point>>,
    monthly: Section<Vec<Point>>,
    yearly: Section<Vec<Point>>,
}

#[derive(Default)]
struct Plots {
    equity: Section<PlotWidget>,
    drawdown: Section<PlotWidget>,
    returns: Section<PlotWidget>,
    rolling_sharpe: Section<PlotWidget>,
    monthly: Section<PlotWidget>,
    yearly: Section<PlotWidget>,
}

impl Plots {
    fn of(&mut self, chart: Chart) -> &mut Section<PlotWidget> {
        match chart {
            Chart::Equity => &mut self.equity,
            Chart::Drawdown => &mut self.drawdown,
            Chart::Returns => &mut self.returns,
            Chart::RollingSharpe => &mut self.rolling_sharpe,
            Chart::Monthly => &mut self.monthly,
            Chart::Yearly => &mut self.yearly,
        }
    }
}

/// The charts of one run, drawn from the data the server computed.
pub struct Charts {
    link: AxisLink,
    data: Data,
    plots: Plots,
}

impl Default for Charts {
    fn default() -> Self {
        Self {
            link: AxisLink::new(),
            data: Data::default(),
            plots: Plots::default(),
        }
    }
}

impl Charts {
    pub fn set(&mut self, chart: Chart, points: Section<Vec<Point>>) {
        match chart {
            Chart::Equity => self.data.equity = points,
            Chart::Drawdown => self.data.drawdown = points,
            Chart::Returns => self.data.returns = points,
            Chart::RollingSharpe => self.data.rolling_sharpe = points,
            Chart::Monthly => self.data.monthly = points,
            Chart::Yearly => self.data.yearly = points,
        }
        self.rebuild();
    }

    pub fn set_benchmark(&mut self, points: Section<Vec<Point>>) {
        self.data.benchmark = points;
        self.rebuild();
    }

    pub fn update(&mut self, message: Message) {
        if let Section::Ready(plot) = self.plots.of(message.chart) {
            plot.update(message.plot);
        }
    }

    pub fn view(&self) -> Element<'_, Message> {
        let plots = &self.plots;
        let charts = [
            (Chart::Equity, &plots.equity),
            (Chart::Drawdown, &plots.drawdown),
            (Chart::Returns, &plots.returns),
            (Chart::RollingSharpe, &plots.rolling_sharpe),
            (Chart::Monthly, &plots.monthly),
            (Chart::Yearly, &plots.yearly),
        ];
        let mut page = column![].spacing(16);
        for (chart, plot) in charts {
            page = page.push(text(chart.title()).size(18));
            page = page.push(self.show(chart, plot));
        }
        page.into()
    }

    fn show<'a>(&'a self, chart: Chart, plot: &'a Section<PlotWidget>) -> Element<'a, Message> {
        match plot {
            Section::Loading => text("Loading...").into(),
            Section::Failed(error) => text(error.as_str()).into(),
            Section::Ready(plot) => {
                let plot = plot.view().map(move |plot| Message { chart, plot });
                let plot = container(plot).height(Length::Fixed(PLOT_HEIGHT));
                match (chart, &self.data.benchmark) {
                    (Chart::Returns, Section::Failed(error)) => {
                        column![plot, text(format!("Benchmark: {error}"))].into()
                    }
                    _ => plot.into(),
                }
            }
        }
    }

    fn rebuild(&mut self) {
        let data = &self.data;
        let link = &self.link;
        let benchmark = match &data.benchmark {
            Section::Ready(points) => points.as_slice(),
            _ => &[],
        };
        self.plots = Plots {
            equity: plot(&data.equity, |points| {
                let line = Line::new("Equity", STRATEGY, points);
                line_plot(&[line], &Axes::dates(Some(link), false))
            }),
            drawdown: plot(&data.drawdown, |points| {
                let line = Line::new("Drawdown", LOSS, points);
                line_plot(&[line], &Axes::dates(Some(link), true))
            }),
            returns: plot(&data.returns, |points| {
                let lines = [
                    Line::new("Returns", STRATEGY, points),
                    Line::new("Benchmark", BENCHMARK, benchmark),
                ];
                line_plot(&lines, &Axes::dates(None, true))
            }),
            rolling_sharpe: plot(&data.rolling_sharpe, |points| {
                let line = Line::new("Sharpe", STRATEGY, points);
                line_plot(&[line], &Axes::dates(None, false))
            }),
            monthly: plot(&data.monthly, heatmap),
            yearly: plot(&data.yearly, bars),
        };
    }
}

fn plot(
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

struct Line<'a> {
    label: &'static str,
    color: Color,
    points: &'a [Point],
}

impl<'a> Line<'a> {
    fn new(label: &'static str, color: Color, points: &'a [Point]) -> Self {
        Self {
            label,
            color,
            points,
        }
    }
}

struct Axes {
    link: Option<AxisLink>,
    percent: bool,
}

impl Axes {
    fn dates(link: Option<&AxisLink>, percent: bool) -> Self {
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

fn line_plot(lines: &[Line<'_>], axes: &Axes) -> Result<PlotWidget, String> {
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

fn heatmap(points: &[Point]) -> Result<PlotWidget, String> {
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

fn bars(points: &[Point]) -> Result<PlotWidget, String> {
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
fn reduce(segment: Vec<[f64; 2]>, limit: usize) -> Vec<[f64; 2]> {
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
fn segments(points: &[Point]) -> Vec<Vec<[f64; 2]>> {
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

fn date_label(seconds: f64) -> String {
    dates::utc_day(seconds.floor() as i64)
}

/// Midnights of UTC days, spaced so that about eight or fewer fall in the range.
fn date_ticks(min: f64, max: f64) -> Vec<f64> {
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

fn ticks(values: Vec<f64>) -> Vec<Tick> {
    let step = values.windows(2).map(|pair| pair[1] - pair[0]).next();
    values
        .into_iter()
        .map(|value| Tick::new(value, step.unwrap_or(1.0), TickWeight::Major))
        .collect()
}

fn integer_ticks(min: f64, max: f64) -> Vec<Tick> {
    let values = (min.ceil() as i64..=max.floor() as i64).map(|value| value as f64);
    ticks(values.collect())
}

fn month_label(month: f64) -> String {
    let index = month.round() as usize;
    MONTHS
        .get(index.wrapping_sub(1))
        .map_or_else(String::new, |name| (*name).to_owned())
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct MonthCell {
    year: i64,
    month: i64,
    value: f64,
}

/// The monthly returns by the UTC year and month of their timestamps, oldest first.
fn monthly_grid(points: &[Point]) -> Vec<MonthCell> {
    points
        .iter()
        .map(|point| {
            let (year, month, _) = dates::civil(point.ts.div_euclid(1_000_000_000));
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
            let (year, _, _) = dates::civil(point.ts.div_euclid(1_000_000_000));
            (year, point.value)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const DAY_NS: i64 = 86_400 * 1_000_000_000;
    const NEW_YEAR_2024: i64 = 1_704_067_200 * 1_000_000_000;

    fn point(ts: i64, value: f64) -> Point {
        Point { ts, value }
    }

    #[test]
    fn a_nan_breaks_the_line_into_segments() {
        let points = [
            point(1_000_000_000, 1.0),
            point(2_000_000_000, 2.0),
            point(3_000_000_000, f64::NAN),
            point(4_000_000_000, 4.0),
            point(5_000_000_000, f64::NAN),
            point(6_000_000_000, f64::NAN),
            point(7_000_000_000, 7.0),
            point(8_000_000_000, 8.0),
        ];

        let segments = segments(&points);

        assert_eq!(
            segments,
            [
                vec![[1.0, 1.0], [2.0, 2.0]],
                vec![[4.0, 4.0]],
                vec![[7.0, 7.0], [8.0, 8.0]],
            ]
        );
    }

    #[test]
    fn a_long_line_is_reduced_to_the_limit_keeping_its_extremes() {
        let line: Vec<[f64; 2]> = (0..10_000)
            .map(|index| [f64::from(index), f64::from(index % 100)])
            .collect();
        let mut line = line;
        line[5_432][1] = 500.0;
        line[7_001][1] = -300.0;

        let reduced = reduce(line, 1_000);

        assert!(reduced.len() <= 1_000);
        assert!(reduced.windows(2).all(|pair| pair[0][0] < pair[1][0]));
        assert!(reduced.iter().any(|point| point[1] == 500.0));
        assert!(reduced.iter().any(|point| point[1] == -300.0));
    }

    #[test]
    fn a_short_line_is_drawn_unchanged() {
        let line: Vec<[f64; 2]> = (0..10).map(|index| [f64::from(index), 1.0]).collect();

        assert_eq!(reduce(line.clone(), 1_000), line);
    }

    #[test]
    fn timestamps_become_utc_date_ticks() {
        let start = NEW_YEAR_2024 as f64 / 1e9 + 3_600.0;
        let end = start + 90.0 * 86_400.0;

        let ticks = date_ticks(start, end);

        assert!((2..=9).contains(&ticks.len()));
        assert!(ticks.iter().all(|tick| *tick >= start && *tick <= end));
        assert!(ticks.iter().all(|tick| tick % 86_400.0 == 0.0));
        assert_eq!(date_label(NEW_YEAR_2024 as f64 / 1e9), "2024-01-01");
        assert_eq!(date_label(1_709_164_799.5), "2024-02-28");
    }

    #[test]
    fn monthly_returns_become_a_year_by_month_grid() {
        let points = [
            point(NEW_YEAR_2024 - DAY_NS, 0.01),
            point(NEW_YEAR_2024 + 30 * DAY_NS, -0.02),
        ];

        let grid = monthly_grid(&points);

        assert_eq!(
            grid,
            [
                MonthCell {
                    year: 2023,
                    month: 12,
                    value: 0.01
                },
                MonthCell {
                    year: 2024,
                    month: 1,
                    value: -0.02
                },
            ]
        );
        assert_eq!(month_label(12.0), "Dec");
    }
}
