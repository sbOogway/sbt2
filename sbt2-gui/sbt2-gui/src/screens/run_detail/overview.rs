//! The overview tab of a run: its header and its metrics.

use iced::{
    Element,
    widget::{column, row, text},
};
use sbt2_client::{
    RunMetrics,
    protocol::{Metric, MetricGroup, RunSummary},
};

use super::Message;
use crate::{format, screens::section::Section};

/// The run's header and its metrics by group.
pub(super) fn view<'a>(
    summary: &'a Section<Box<RunSummary>>,
    metrics: &'a Section<RunMetrics>,
) -> Element<'a, Message> {
    column![header(summary), self::metrics(metrics)]
        .spacing(16)
        .into()
}

fn header(summary: &Section<Box<RunSummary>>) -> Element<'_, Message> {
    match summary {
        Section::Loading => text("Loading the run...").into(),
        Section::Failed(error) => text(format!("Could not load the run: {error}")).into(),
        Section::Ready(run) => labelled(header_lines(run)),
    }
}

fn metrics(metrics: &Section<RunMetrics>) -> Element<'_, Message> {
    match metrics {
        Section::Loading => text("Loading the metrics...").into(),
        Section::Failed(error) => text(format!("Could not load the metrics: {error}")).into(),
        Section::Ready(metrics) => {
            let groups = metric_groups(metrics).into_iter().map(|(title, lines)| {
                column![text(title).size(18), labelled(lines)]
                    .spacing(4)
                    .into()
            });
            column(groups).spacing(12).into()
        }
    }
}

fn labelled<'a>(lines: Vec<(String, String)>) -> Element<'a, Message> {
    let rows = lines
        .into_iter()
        .map(|(label, value)| row![text(label).width(280), text(value)].spacing(12).into());
    column(rows).into()
}

fn header_lines(run: &RunSummary) -> Vec<(String, String)> {
    let day = |seconds: Option<i64>| seconds.map(format::utc_day).unwrap_or_default();
    let start = day(run.start_at.as_ref().map(|at| at.seconds));
    let end = day(run.end_at.as_ref().map(|at| at.seconds));
    let tripped = day(run.drawdown_tripped_at.as_ref().map(|at| at.seconds));
    let lines = [
        ("Strategy", run.strategy.clone()),
        ("Parameters", run.params_json.clone()),
        ("Part", run.part.clone()),
        ("Period", format!("{start} to {end}")),
        ("Instruments", run.instruments.join(", ")),
        ("Known gaps", run.known_gaps.join(", ")),
        ("Drawdown trip", tripped),
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
fn metric_groups(metrics: &RunMetrics) -> Vec<(String, Vec<(String, String)>)> {
    let mut groups: Vec<(i32, Vec<(String, String)>)> = Vec::new();
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
}
