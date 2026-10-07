//! The fills of a run as a table of pages that sorts by any column.

use std::cmp::Ordering;

use iced::{
    Element, Length,
    widget::{button, column, row, text},
};
use sbt2_client::{Cell, Table};

use crate::format;

const PAGE_SIZE: usize = 500;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Direction {
    Ascending,
    Descending,
}

#[derive(Debug, Clone)]
pub enum Message {
    Sort(usize),
    Next,
    Previous,
}

enum Key {
    Number(f64),
    Text(String),
}

fn compare(left: &Option<Key>, right: &Option<Key>) -> Ordering {
    match (left, right) {
        (Some(Key::Number(left)), Some(Key::Number(right))) => left.total_cmp(right),
        (Some(Key::Text(left)), Some(Key::Text(right))) => left.cmp(right),
        _ => left.is_some().cmp(&right.is_some()),
    }
}

/// The fills as the server stored them; all rows stay in memory, one page shows at a time.
#[derive(Debug, Default)]
pub struct FillsTable {
    table: Table,
    order: Vec<usize>,
    sort: Option<(usize, Direction)>,
    page: usize,
}

impl FillsTable {
    pub fn new(table: Table) -> Self {
        let order = (0..table.rows.len()).collect();
        Self {
            table,
            order,
            sort: None,
            page: 0,
        }
    }

    pub fn update(&mut self, message: Message) {
        match message {
            Message::Sort(column) => self.sort_by(column),
            Message::Next => self.page = (self.page + 1).min(self.last_page()),
            Message::Previous => self.page = self.page.saturating_sub(1),
        }
    }

    pub fn view(&self) -> Element<'_, Message> {
        let rows = self.page_rows().into_iter().map(|cells| {
            let cells = cells
                .iter()
                .map(|cell| text(show(cell)).width(Length::Fill).into());
            row(cells).padding([2, 10]).into()
        });
        column![self.toolbar(), self.header(), column(rows)]
            .spacing(8)
            .into()
    }

    fn page_rows(&self) -> Vec<&Vec<Cell>> {
        self.order
            .iter()
            .skip(self.page * PAGE_SIZE)
            .take(PAGE_SIZE)
            .map(|index| &self.table.rows[*index])
            .collect()
    }

    fn last_page(&self) -> usize {
        self.order.len().saturating_sub(1) / PAGE_SIZE
    }

    fn sort_by(&mut self, column: usize) {
        let direction = match self.sort {
            Some((current, Direction::Ascending)) if current == column => Direction::Descending,
            _ => Direction::Ascending,
        };
        self.sort = Some((column, direction));
        self.page = 0;
        let keys = self.keys(column);
        self.order.sort_by(|left, right| {
            let order = compare(&keys[*left], &keys[*right]);
            match direction {
                Direction::Ascending => order,
                Direction::Descending => order.reverse(),
            }
        });
    }

    /// The sort keys of a column by row; a text column is numeric when all its values parse.
    fn keys(&self, column: usize) -> Vec<Option<Key>> {
        let cells = self.table.rows.iter().map(|cells| &cells[column]);
        let numbers: Vec<_> = cells.clone().map(number).collect();
        let numeric = cells
            .clone()
            .zip(&numbers)
            .all(|(cell, number)| matches!(cell, Cell::Null) || number.is_some());
        cells
            .zip(numbers)
            .map(|(cell, number)| match cell {
                Cell::Null => None,
                _ if numeric => number.map(Key::Number),
                _ => Some(Key::Text(show(cell))),
            })
            .collect()
    }

    fn toolbar(&self) -> Element<'_, Message> {
        let first = self.page * PAGE_SIZE + 1;
        let last = ((self.page + 1) * PAGE_SIZE).min(self.order.len());
        let status = if self.order.is_empty() {
            "No fills".to_owned()
        } else {
            format!("Fills {first} to {last} of {}", self.order.len())
        };
        row![
            button("Previous").on_press_maybe((self.page > 0).then_some(Message::Previous)),
            button("Next").on_press_maybe((self.page < self.last_page()).then_some(Message::Next)),
            text(status),
        ]
        .spacing(12)
        .into()
    }

    fn header(&self) -> Element<'_, Message> {
        let titles = self.table.columns.iter().enumerate().map(|(index, name)| {
            let arrow = match self.sort {
                Some((sorted, Direction::Ascending)) if sorted == index => " ^",
                Some((sorted, Direction::Descending)) if sorted == index => " v",
                _ => "",
            };
            button(text(format!("{name}{arrow}")))
                .on_press(Message::Sort(index))
                .width(Length::Fill)
                .style(button::text)
                .into()
        });
        row(titles).into()
    }
}

fn number(cell: &Cell) -> Option<f64> {
    match cell {
        Cell::Int(value) => Some(*value as f64),
        Cell::Float(value) => Some(*value),
        Cell::Time(nanos) => Some(*nanos as f64),
        Cell::Bool(value) => Some(f64::from(u8::from(*value))),
        Cell::Text(text) => text.parse().ok(),
        Cell::Null => None,
    }
}

fn show(cell: &Cell) -> String {
    match cell {
        Cell::Null => String::new(),
        Cell::Int(value) => value.to_string(),
        Cell::Float(value) => value.to_string(),
        Cell::Text(text) => text.clone(),
        Cell::Time(nanos) => format::utc_datetime(*nanos),
        Cell::Bool(value) => value.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table(rows: Vec<Vec<Cell>>) -> FillsTable {
        let columns = vec!["id".to_owned(), "last_px".to_owned()];
        FillsTable::new(Table { columns, rows })
    }

    fn text_rows(prices: &[Option<&str>]) -> FillsTable {
        let rows = prices
            .iter()
            .enumerate()
            .map(|(index, price)| {
                let price = price.map_or(Cell::Null, |price| Cell::Text(price.to_owned()));
                vec![Cell::Int(index as i64), price]
            })
            .collect();
        table(rows)
    }

    fn ids(fills: &FillsTable) -> Vec<i64> {
        fills
            .page_rows()
            .iter()
            .map(|cells| match cells[0] {
                Cell::Int(id) => id,
                _ => panic!("the first column holds integers"),
            })
            .collect()
    }

    #[test]
    fn fills_are_paged_by_500() {
        let rows = (0..1_200)
            .map(|id| vec![Cell::Int(id), Cell::Null])
            .collect();
        let mut fills = table(rows);
        assert_eq!(fills.page_rows().len(), 500);
        assert_eq!(ids(&fills)[0], 0);

        fills.update(Message::Next);
        assert_eq!(ids(&fills)[0], 500);

        fills.update(Message::Next);
        assert_eq!(fills.page_rows().len(), 200);

        fills.update(Message::Next);
        assert_eq!(ids(&fills)[0], 1_000);

        fills.update(Message::Previous);
        fills.update(Message::Previous);
        fills.update(Message::Previous);
        assert_eq!(ids(&fills)[0], 0);
    }

    #[test]
    fn numeric_text_columns_sort_as_numbers() {
        let mut fills = text_rows(&[Some("10"), Some("9"), None, Some("2.5")]);

        fills.update(Message::Sort(1));
        assert_eq!(ids(&fills), [2, 3, 1, 0]);

        fills.update(Message::Sort(1));
        assert_eq!(ids(&fills), [0, 1, 3, 2]);

        let mut words = text_rows(&[Some("b"), Some("10"), Some("a")]);
        words.update(Message::Sort(1));
        assert_eq!(ids(&words), [1, 2, 0]);
    }

    #[test]
    fn sorting_returns_to_the_first_page() {
        let rows = (0..600)
            .map(|id| vec![Cell::Int(id), Cell::Int(-id)])
            .collect();
        let mut fills = table(rows);
        fills.update(Message::Next);
        assert_eq!(fills.page, 1);

        fills.update(Message::Sort(1));

        assert_eq!(fills.page, 0);
        assert_eq!(ids(&fills)[0], 599);
    }
}
