//! The overview tab of a run: its header and its metrics.

use iced::{
    Element, Length,
    widget::{column, container, responsive, row, text},
};
use iced_aw::{Badge, Card, style::badge};
use sbt2_client::{
    RunMetrics,
    protocol::{Metric, MetricGroup, RunSummary},
};

use super::Message;
use crate::{format, screens::section::Section, style};

/// Below this width the tiles go in one column.
const WIDE_WINDOW: f32 = 900.0;

type Lines = Vec<(String, String)>;
type Group = (String, Lines);

/// The run's header and its metrics by group, as a bento of cards.
pub(super) fn view<'a>(
    summary: &'a Section<Box<RunSummary>>,
    metrics: &'a Section<RunMetrics>,
) -> Element<'a, Message> {
    responsive(move |size| {
        let columns = tile_columns(size.width);
        column![header(summary), self::metrics(metrics, columns)]
            .spacing(style::GAP)
            .into()
    })
    .into()
}

fn tile_columns(width: f32) -> usize {
    if width < WIDE_WINDOW { 1 } else { 2 }
}

/// Gives each group, in order, to the column with the fewest lines so far.
fn spread(groups: Vec<Group>, columns: usize) -> Vec<Vec<Group>> {
    let mut spread: Vec<(usize, Vec<Group>)> = (0..columns).map(|_| (0, Vec::new())).collect();
    for group in groups {
        let (lines, column) = spread
            .iter_mut()
            .min_by_key(|(lines, _)| *lines)
            .expect("at least one column");
        *lines += group.1.len();
        column.push(group);
    }
    spread.into_iter().map(|(_, column)| column).collect()
}

fn header(summary: &Section<Box<RunSummary>>) -> Element<'_, Message> {
    match summary {
        Section::Loading => text("Loading the run...").into(),
        Section::Failed(error) => text(format!("Could not load the run: {error}")).into(),
        Section::Ready(run) => tile("Run", run_body(run)),
    }
}

fn metrics(metrics: &Section<RunMetrics>, columns: usize) -> Element<'_, Message> {
    match metrics {
        Section::Loading => text("Loading the metrics...").into(),
        Section::Failed(error) => text(format!("Could not load the metrics: {error}")).into(),
        Section::Ready(metrics) => bento(spread(metric_groups(metrics), columns)),
    }
}

fn bento<'a>(columns: Vec<Vec<Group>>) -> Element<'a, Message> {
    let columns = columns.into_iter().map(|groups| {
        let tiles = groups
            .into_iter()
            .map(|(title, lines)| tile(&title, labelled(lines)));
        column(tiles)
            .spacing(style::GAP)
            .width(Length::FillPortion(1))
            .into()
    });
    row(columns).spacing(style::GAP).into()
}

fn tile<'a>(title: &str, body: Element<'a, Message>) -> Element<'a, Message> {
    let card = Card::new(text(title.to_owned()).size(18), body);
    container(card).width(Length::Fill).into()
}

fn labelled<'a>(lines: Lines) -> Element<'a, Message> {
    let rows = lines
        .into_iter()
        .map(|(label, value)| row![text(label).width(280), text(value)].spacing(12).into());
    column(rows).into()
}

fn run_body<'a>(run: &RunSummary) -> Element<'a, Message> {
    let tripped = day(run.drawdown_tripped_at.as_ref().map(|at| at.seconds));
    let value: Element<'a, Message> = if tripped.is_empty() {
        text(tripped).into()
    } else {
        Badge::new(text(tripped)).style(badge::danger).into()
    };
    let trip = row![text("Drawdown trip").width(280), value].spacing(12);
    column![labelled(header_lines(run)), trip].into()
}

fn day(seconds: Option<i64>) -> String {
    seconds.map(format::utc_day).unwrap_or_default()
}

fn header_lines(run: &RunSummary) -> Lines {
    let start = day(run.start_at.as_ref().map(|at| at.seconds));
    let end = day(run.end_at.as_ref().map(|at| at.seconds));
    let lines = [
        ("Strategy", run.strategy.clone()),
        ("Parameters", run.params_json.clone()),
        ("Part", run.part.clone()),
        ("Period", format!("{start} to {end}")),
        ("Instruments", run.instruments.join(", ")),
        ("Known gaps", run.known_gaps.join(", ")),
    ];
    lines
        .into_iter()
        .map(|(label, value)| (label.to_owned(), value))
        .collect()
}

fn group_title(group: i32) -> &'static str {
    match MetricGroup::try_from(group) {
        Ok(MetricGroup::Pnls) => "PnLs",
        Ok(MetricGroup::Returns) => "Returns",
        Ok(MetricGroup::General) => "General",
        Ok(MetricGroup::InstrumentPnls) => "Instrument PnLs",
        Ok(MetricGroup::ProbabilisticSharpe) => "Probabilistic Sharpe",
        _ => "Other",
    }
}

fn metric_label(metric: &Metric) -> String {
    match &metric.instrument_id {
        Some(instrument) => format!("{} ({instrument})", metric.name),
        None => metric.name.clone(),
    }
}

/// The metrics as titled lines of label and value; an undefined value is blank.
fn metric_groups(metrics: &RunMetrics) -> Vec<Group> {
    let mut groups: Vec<(i32, Lines)> = Vec::new();
    for metric in &metrics.entries {
        let value = metric.value.clone().unwrap_or_default();
        let line = (metric_label(metric), value);
        match groups.iter_mut().find(|(group, _)| *group == metric.group) {
            Some((_, lines)) => lines.push(line),
            None => groups.push((metric.group, vec![line])),
        }
    }
    groups.sort_by_key(|(group, _)| *group);
    groups
        .into_iter()
        .map(|(group, lines)| (group_title(group).to_owned(), lines))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn metric(group: MetricGroup, name: &str, value: Option<&str>) -> Metric {
        Metric {
            group: group as i32,
            name: name.to_owned(),
            value: value.map(str::to_owned),
            instrument_id: None,
        }
    }

    fn group(title: &str, lines: usize) -> Group {
        let lines = (0..lines)
            .map(|index| (format!("line {index}"), String::new()))
            .collect();
        (title.to_owned(), lines)
    }

    fn titles(column: &[Group]) -> Vec<&str> {
        column.iter().map(|(title, _)| title.as_str()).collect()
    }

    #[test]
    fn an_undefined_metric_shows_blank() {
        let metrics = RunMetrics {
            currency: "USD".to_owned(),
            entries: vec![
                metric(MetricGroup::Returns, "Sharpe", None),
                metric(MetricGroup::Returns, "Sortino", Some("1.5")),
                metric(MetricGroup::Pnls, "PnL", Some("0")),
            ],
        };

        let groups = metric_groups(&metrics);

        assert_eq!(groups[0].0, "PnLs");
        assert_eq!(groups[0].1, [("PnL".to_owned(), "0".to_owned())]);
        assert_eq!(groups[1].0, "Returns");
        assert_eq!(
            groups[1].1,
            [
                ("Sharpe".to_owned(), String::new()),
                ("Sortino".to_owned(), "1.5".to_owned())
            ]
        );
    }

    #[test]
    fn a_narrow_window_puts_the_tiles_in_one_column() {
        assert_eq!(tile_columns(899.0), 1);
    }

    #[test]
    fn a_wide_window_puts_the_tiles_in_two_columns() {
        assert_eq!(tile_columns(900.0), 2);
    }

    #[test]
    fn the_metric_groups_are_balanced_over_the_columns() {
        let groups = vec![group("a", 6), group("b", 3), group("c", 2), group("d", 1)];

        let columns = spread(groups, 2);

        assert_eq!(titles(&columns[0]), ["a"]);
        assert_eq!(titles(&columns[1]), ["b", "c", "d"]);
    }

    #[test]
    fn one_column_keeps_the_groups_in_order() {
        let groups = vec![group("a", 6), group("b", 3), group("c", 2)];

        let columns = spread(groups, 1);

        assert_eq!(columns.len(), 1);
        assert_eq!(titles(&columns[0]), ["a", "b", "c"]);
    }
}
