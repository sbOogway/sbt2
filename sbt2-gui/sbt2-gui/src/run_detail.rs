//! The detail of one run: its header and metrics, and a cache of what was loaded.

use std::collections::{HashMap, HashSet};

use iced::{
    Element,
    widget::{button, column, row, scrollable, text},
};
use sbt2_client::{
    ClientError, RunMetrics, Session, Table,
    protocol::{Metric, MetricGroup, RunSummary},
};

use crate::{
    dates,
    fills_table::{self, FillsTable},
    section::Section,
};

/// A request the detail needs a client call for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Load {
    Summary,
    Metrics,
    Fills,
}

impl Load {
    /// Asks the server for this part of a run.
    pub async fn fetch(self, session: &Session, run_id: &str) -> Loaded {
        match self {
            Self::Summary => Loaded::Summary(session.get_run(run_id).await.map(Box::new)),
            Self::Metrics => Loaded::Metrics(session.get_metrics(run_id).await),
            Self::Fills => Loaded::Fills(session.get_fills(run_id).await),
        }
    }
}

/// The answer to a `Load`.
#[derive(Debug, Clone)]
pub enum Loaded {
    Summary(Result<Box<RunSummary>, ClientError>),
    Metrics(Result<RunMetrics, ClientError>),
    Fills(Result<Table, ClientError>),
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash)]
pub enum Tab {
    #[default]
    Overview,
    Fills,
}

impl Tab {
    const ALL: [Self; 2] = [Self::Overview, Self::Fills];

    fn title(self) -> &'static str {
        match self {
            Self::Overview => "Overview",
            Self::Fills => "Fills",
        }
    }

    fn loads(self) -> Vec<Load> {
        match self {
            Self::Overview => vec![Load::Summary, Load::Metrics],
            Self::Fills => vec![Load::Fills],
        }
    }
}

#[derive(Debug, Clone)]
pub enum Message {
    Back,
    Refresh,
    Show(Tab),
    Fills(fills_table::Message),
    Loaded(String, Loaded),
}

#[derive(Default)]
struct RunData {
    summary: Section<Box<RunSummary>>,
    metrics: Section<RunMetrics>,
    fills: Section<FillsTable>,
    opened: HashSet<Tab>,
}

impl RunData {
    fn apply(&mut self, loaded: Loaded) {
        match loaded {
            Loaded::Summary(result) => self.summary = result.into(),
            Loaded::Metrics(result) => self.metrics = result.into(),
            Loaded::Fills(result) => self.fills = result.map(FillsTable::new).into(),
        }
    }
}

/// The run shown in place of the runs table, and the data of every run opened this session.
#[derive(Default)]
pub struct RunDetail {
    runs: HashMap<String, RunData>,
    open: Option<String>,
    tab: Tab,
}

impl RunDetail {
    pub fn is_open(&self) -> bool {
        self.open.is_some()
    }

    pub fn run_id(&self) -> Option<&str> {
        self.open.as_deref()
    }

    /// Shows a run; returns the loads it needs, none when its data is cached.
    pub fn open(&mut self, run_id: &str) -> Vec<Load> {
        self.open = Some(run_id.to_owned());
        self.tab = Tab::Overview;
        if self.runs.contains_key(run_id) {
            return Vec::new();
        }
        let mut data = RunData::default();
        data.opened.insert(Tab::Overview);
        self.runs.insert(run_id.to_owned(), data);
        Tab::Overview.loads()
    }

    /// Applies a message; returns the loads the caller must start.
    pub fn update(&mut self, message: Message) -> Vec<Load> {
        match message {
            Message::Back => self.open = None,
            Message::Refresh => return self.reload(),
            Message::Show(tab) => return self.show(tab),
            Message::Fills(message) => self.update_fills(message),
            Message::Loaded(run_id, loaded) => {
                if let Some(data) = self.runs.get_mut(&run_id) {
                    data.apply(loaded);
                }
            }
        }
        Vec::new()
    }

    pub fn view(&self) -> Element<'_, Message> {
        let toolbar = row![
            button("Back").on_press(Message::Back),
            button("Refresh").on_press(Message::Refresh),
        ]
        .spacing(12);
        let body = match self.data() {
            Some(data) => self.tab_view(data),
            None => text("No run is open.").into(),
        };
        column![toolbar, self.tabs(), scrollable(body)]
            .spacing(12)
            .into()
    }

    fn data(&self) -> Option<&RunData> {
        self.runs.get(self.open.as_deref()?)
    }

    fn data_mut(&mut self) -> Option<&mut RunData> {
        self.runs.get_mut(self.open.as_deref()?)
    }

    fn show(&mut self, tab: Tab) -> Vec<Load> {
        self.tab = tab;
        let first_time = self.data_mut().is_some_and(|data| data.opened.insert(tab));
        if first_time { tab.loads() } else { Vec::new() }
    }

    fn reload(&self) -> Vec<Load> {
        let Some(data) = self.data() else {
            return Vec::new();
        };
        Tab::ALL
            .into_iter()
            .filter(|tab| data.opened.contains(tab))
            .flat_map(Tab::loads)
            .collect()
    }

    fn update_fills(&mut self, message: fills_table::Message) {
        if let Some(Section::Ready(fills)) = self.data_mut().map(|data| &mut data.fills) {
            fills.update(message);
        }
    }

    fn tabs(&self) -> Element<'_, Message> {
        let tabs = Tab::ALL.map(|tab| {
            button(tab.title())
                .on_press_maybe((tab != self.tab).then_some(Message::Show(tab)))
                .into()
        });
        row(tabs).spacing(8).into()
    }

    fn tab_view<'a>(&self, data: &'a RunData) -> Element<'a, Message> {
        match self.tab {
            Tab::Overview => overview(data),
            Tab::Fills => fills(&data.fills),
        }
    }
}

fn fills(fills: &Section<FillsTable>) -> Element<'_, Message> {
    match fills {
        Section::Loading => text("Loading the fills...").into(),
        Section::Failed(error) => text(format!("Could not load the fills: {error}")).into(),
        Section::Ready(fills) => fills.view().map(Message::Fills),
    }
}

fn overview(data: &RunData) -> Element<'_, Message> {
    column![header(&data.summary), metrics(&data.metrics)]
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
    let day = |seconds: Option<i64>| seconds.map(dates::utc_day).unwrap_or_default();
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
    fn opening_a_run_loads_only_the_overview() {
        let mut detail = RunDetail::default();

        let loads = detail.open("a");

        assert_eq!(loads, [Load::Summary, Load::Metrics]);
        assert_eq!(detail.run_id(), Some("a"));
    }

    #[test]
    fn a_cached_run_opens_without_new_loads() {
        let mut detail = RunDetail::default();
        detail.open("a");
        detail.update(Message::Back);
        assert!(!detail.is_open());

        assert_eq!(detail.open("a"), []);
        assert_eq!(detail.open("b"), [Load::Summary, Load::Metrics]);
    }

    #[test]
    fn a_tab_loads_its_data_the_first_time_it_opens() {
        let mut detail = RunDetail::default();
        detail.open("a");

        assert_eq!(detail.update(Message::Show(Tab::Fills)), [Load::Fills]);
        assert_eq!(detail.update(Message::Show(Tab::Overview)), []);
        assert_eq!(detail.update(Message::Show(Tab::Fills)), []);
    }

    #[test]
    fn refresh_loads_the_opened_tabs_again() {
        let mut detail = RunDetail::default();
        detail.open("a");
        assert_eq!(
            detail.update(Message::Refresh),
            [Load::Summary, Load::Metrics]
        );

        detail.update(Message::Show(Tab::Fills));

        assert_eq!(
            detail.update(Message::Refresh),
            [Load::Summary, Load::Metrics, Load::Fills]
        );
    }

    #[test]
    fn a_failed_load_keeps_its_error_in_its_own_section() {
        let mut detail = RunDetail::default();
        detail.open("a");
        let summary = RunSummary {
            strategy: "momentum".to_owned(),
            ..RunSummary::default()
        };

        detail.update(Message::Loaded(
            "a".to_owned(),
            Loaded::Summary(Ok(Box::new(summary))),
        ));
        detail.update(Message::Loaded(
            "a".to_owned(),
            Loaded::Metrics(Err(ClientError::Disconnected)),
        ));

        let data = detail.data().unwrap();
        assert!(matches!(&data.summary, Section::Ready(run) if run.strategy == "momentum"));
        assert_eq!(
            data.metrics,
            Section::Failed("the connection is down".to_owned())
        );
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
