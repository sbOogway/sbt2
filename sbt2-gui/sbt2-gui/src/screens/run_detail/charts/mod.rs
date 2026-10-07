//! The tearsheet charts of a run. Only this module and its submodules use `iced_plot`.

use iced::{
    Element, Length,
    widget::{column, container, text},
};
use iced_plot::{AxisLink, PlotUiMessage, PlotWidget};
use sbt2_client::Point;

mod plots;
mod ticks;

use self::plots::{Axes, BENCHMARK, LOSS, Line, STRATEGY, bars, heatmap, line_plot, plot};
use crate::screens::section::Section;

const PLOT_HEIGHT: f32 = 300.0;
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

#[cfg(test)]
mod tests {
    use super::{
        plots::{MonthCell, monthly_grid, reduce, segments},
        ticks::{date_label, date_ticks, month_label},
        *,
    };

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
