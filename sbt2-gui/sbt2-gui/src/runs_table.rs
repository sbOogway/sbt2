use std::cmp::Ordering;

use iced::{
    Element, Length,
    widget::{button, column, row, scrollable, text},
};
use sbt2_client::{ClientError, protocol::RunSummary};

use crate::dates;

const NO_VALUE: &str = "-";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Column {
    Strategy,
    Part,
    Instruments,
    Start,
    End,
    NetReturn,
    AnnualizedReturn,
    Sharpe,
    MaxDrawdown,
    Trades,
    Fees,
}

impl Column {
    const ALL: [Self; 11] = [
        Self::Strategy,
        Self::Part,
        Self::Instruments,
        Self::Start,
        Self::End,
        Self::NetReturn,
        Self::AnnualizedReturn,
        Self::Sharpe,
        Self::MaxDrawdown,
        Self::Trades,
        Self::Fees,
    ];

    fn title(self) -> &'static str {
        match self {
            Self::Strategy => "Strategy",
            Self::Part => "Part",
            Self::Instruments => "Instruments",
            Self::Start => "Start",
            Self::End => "End",
            Self::NetReturn => "Net return",
            Self::AnnualizedReturn => "Annualized",
            Self::Sharpe => "Sharpe",
            Self::MaxDrawdown => "Max drawdown",
            Self::Trades => "Trades",
            Self::Fees => "Fees",
        }
    }

    fn portion(self) -> u16 {
        match self {
            Self::Strategy | Self::Instruments => 3,
            _ => 2,
        }
    }

    fn key(self, run: &RunSummary) -> Key {
        let headline = run.headline.clone().unwrap_or_default();
        match self {
            Self::Strategy => Key::Text(run.strategy.clone()),
            Self::Part => Key::Text(run.part.clone()),
            Self::Instruments => Key::Text(run.instruments.join(", ")),
            Self::Start => Key::Number(run.start_at.as_ref().map(|at| at.seconds as f64)),
            Self::End => Key::Number(run.end_at.as_ref().map(|at| at.seconds as f64)),
            Self::NetReturn => number(headline.net_return.as_deref()),
            Self::AnnualizedReturn => number(headline.annualized_return.as_deref()),
            Self::Sharpe => number(headline.sharpe.as_deref()),
            Self::MaxDrawdown => number(headline.max_drawdown.as_deref()),
            Self::Trades => Key::Number(Some(headline.trade_count as f64)),
            Self::Fees => number(Some(&headline.total_fees)),
        }
    }

    fn cell(self, run: &RunSummary) -> String {
        let headline = run.headline.clone().unwrap_or_default();
        match self {
            Self::Strategy => run.strategy.clone(),
            Self::Part => run.part.clone(),
            Self::Instruments => run.instruments.join(", "),
            Self::Start => date(run.start_at.as_ref().map(|at| at.seconds)),
            Self::End => date(run.end_at.as_ref().map(|at| at.seconds)),
            Self::NetReturn => percent(headline.net_return.as_deref()),
            Self::AnnualizedReturn => percent(headline.annualized_return.as_deref()),
            Self::Sharpe => fixed(headline.sharpe.as_deref(), 2),
            Self::MaxDrawdown => percent(headline.max_drawdown.as_deref()),
            Self::Trades => headline.trade_count.to_string(),
            Self::Fees => fixed(Some(&headline.total_fees), 2),
        }
    }
}

enum Key {
    Text(String),
    Number(Option<f64>),
}

fn number(value: Option<&str>) -> Key {
    Key::Number(value.and_then(|text| text.parse().ok()))
}

fn compare(left: &Key, right: &Key) -> Ordering {
    match (left, right) {
        (Key::Text(left), Key::Text(right)) => left.cmp(right),
        (Key::Number(left), Key::Number(right)) => match (left, right) {
            (Some(left), Some(right)) => left.total_cmp(right),
            _ => left.is_some().cmp(&right.is_some()),
        },
        _ => Ordering::Equal,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    Ascending,
    Descending,
}

#[derive(Debug, Clone)]
pub enum Message {
    Sort(Column),
    Refresh,
    Loaded(Result<Vec<RunSummary>, ClientError>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Load {
    Loading,
    Loaded,
    Failed(String),
}

/// The runs of the server, sorted on the client by the column last clicked.
#[derive(Debug)]
pub struct RunsTable {
    runs: Vec<RunSummary>,
    sort: Option<(Column, Direction)>,
    load: Load,
}

impl Default for RunsTable {
    fn default() -> Self {
        Self {
            runs: Vec::new(),
            sort: None,
            load: Load::Loading,
        }
    }
}

impl RunsTable {
    /// Applies a message; `true` when the caller must load the runs again.
    pub fn update(&mut self, message: Message) -> bool {
        match message {
            Message::Sort(column) => self.sort_by(column),
            Message::Refresh => {
                self.load = Load::Loading;
                return true;
            }
            Message::Loaded(Ok(runs)) => {
                self.runs = runs;
                self.load = Load::Loaded;
            }
            Message::Loaded(Err(error)) => self.load = Load::Failed(error.to_string()),
        }
        false
    }

    pub fn view(&self) -> Element<'_, Message> {
        let status = match &self.load {
            Load::Loading => "Loading runs...".to_owned(),
            Load::Loaded => format!("{} runs", self.runs.len()),
            Load::Failed(error) => format!("Could not load the runs: {error}"),
        };
        let toolbar = row![button("Refresh").on_press(Message::Refresh), text(status)].spacing(12);
        column![toolbar, self.header(), scrollable(self.rows())]
            .spacing(8)
            .into()
    }

    fn sort_by(&mut self, column: Column) {
        let direction = match self.sort {
            Some((current, Direction::Ascending)) if current == column => Direction::Descending,
            _ => Direction::Ascending,
        };
        self.sort = Some((column, direction));
    }

    fn sorted(&self) -> Vec<&RunSummary> {
        let mut runs: Vec<_> = self.runs.iter().collect();
        if let Some((column, direction)) = self.sort {
            runs.sort_by(|left, right| {
                let order = compare(&column.key(left), &column.key(right));
                match direction {
                    Direction::Ascending => order,
                    Direction::Descending => order.reverse(),
                }
            });
        }
        runs
    }

    fn header(&self) -> Element<'_, Message> {
        let titles = Column::ALL.map(|column| {
            let arrow = match self.sort {
                Some((sorted, Direction::Ascending)) if sorted == column => " ^",
                Some((sorted, Direction::Descending)) if sorted == column => " v",
                _ => "",
            };
            button(text(format!("{}{arrow}", column.title())))
                .on_press(Message::Sort(column))
                .width(Length::FillPortion(column.portion()))
                .style(button::text)
                .into()
        });
        row(titles).into()
    }

    fn rows(&self) -> Element<'_, Message> {
        let rows = self.sorted().into_iter().map(|run| {
            let cells = Column::ALL.map(|column| {
                text(column.cell(run))
                    .width(Length::FillPortion(column.portion()))
                    .into()
            });
            row(cells).padding([2, 10]).into()
        });
        column(rows).into()
    }
}

fn percent(value: Option<&str>) -> String {
    value.and_then(|text| text.parse::<f64>().ok()).map_or_else(
        || NO_VALUE.to_owned(),
        |fraction| format!("{:.2}%", fraction * 100.0),
    )
}

fn fixed(value: Option<&str>, places: usize) -> String {
    value.and_then(|text| text.parse::<f64>().ok()).map_or_else(
        || NO_VALUE.to_owned(),
        |number| format!("{number:.places$}"),
    )
}

fn date(seconds: Option<i64>) -> String {
    seconds.map_or_else(|| NO_VALUE.to_owned(), dates::utc_day)
}

#[cfg(test)]
mod tests {
    use sbt2_client::protocol::HeadlineMetrics;

    use super::*;

    fn run(id: &str, strategy: &str, trades: u64) -> RunSummary {
        RunSummary {
            run_id: id.to_owned(),
            strategy: strategy.to_owned(),
            headline: Some(HeadlineMetrics {
                trade_count: trades,
                ..HeadlineMetrics::default()
            }),
            ..RunSummary::default()
        }
    }

    fn table(runs: Vec<RunSummary>) -> RunsTable {
        let mut table = RunsTable::default();
        table.update(Message::Loaded(Ok(runs)));
        table
    }

    fn order(table: &RunsTable) -> Vec<&str> {
        table
            .sorted()
            .iter()
            .map(|run| run.run_id.as_str())
            .collect()
    }

    #[test]
    fn the_runs_table_sorts_by_the_clicked_column_and_toggles_direction() {
        let mut table = table(vec![run("a", "z", 3), run("b", "x", 1), run("c", "y", 2)]);
        assert_eq!(order(&table), ["a", "b", "c"]);

        table.update(Message::Sort(Column::Trades));
        assert_eq!(order(&table), ["b", "c", "a"]);

        table.update(Message::Sort(Column::Trades));
        assert_eq!(order(&table), ["a", "c", "b"]);

        table.update(Message::Sort(Column::Strategy));
        assert_eq!(order(&table), ["b", "c", "a"]);
    }

    #[test]
    fn undefined_metrics_sort_first_and_show_a_dash() {
        let mut defined = run("defined", "s", 0);
        defined.headline.as_mut().unwrap().sharpe = Some("1.5".to_owned());
        let mut table = table(vec![defined, run("undefined", "s", 0)]);

        table.update(Message::Sort(Column::Sharpe));

        assert_eq!(order(&table), ["undefined", "defined"]);
        assert_eq!(Column::Sharpe.cell(&run("x", "s", 0)), "-");
        assert_eq!(fixed(Some("1.5"), 2), "1.50");
    }

    #[test]
    fn refresh_asks_for_a_new_load_and_a_failure_keeps_the_old_rows() {
        let mut table = table(vec![run("a", "s", 1)]);

        assert!(table.update(Message::Refresh));
        let failed = table.update(Message::Loaded(Err(ClientError::Disconnected)));

        assert!(!failed);
        assert_eq!(order(&table), ["a"]);
        assert_eq!(
            table.load,
            Load::Failed("the connection is down".to_owned())
        );
    }

    #[test]
    fn dates_show_as_utc_days() {
        assert_eq!(date(Some(1_704_067_200)), "2024-01-01");
        assert_eq!(date(None), "-");
        assert_eq!(percent(Some("0.0123")), "1.23%");
    }
}
