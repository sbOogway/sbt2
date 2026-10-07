//! The form that connects to a server, shown until one answers.

use iced::{
    Element, Length,
    widget::{button, column, container, text, text_input},
};

use crate::app::Message;

const URL_INPUT: &str = "server-url";
const TOKEN_INPUT: &str = "server-token";

/// What the user typed.
#[derive(Debug, Default)]
pub struct Form {
    pub url: String,
    pub token: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Status {
    Idle,
    Connecting,
    Failed(String),
}

impl Status {
    fn text(&self) -> String {
        match self {
            Self::Idle => String::new(),
            Self::Connecting => "Connecting...".to_owned(),
            Self::Failed(error) => format!("Connection failed: {error}"),
        }
    }
}

/// The form, its status and the `warnings` of the last connection.
pub fn view<'a>(
    form: &'a Form,
    status: &Status,
    warnings: impl Iterator<Item = String>,
) -> Element<'a, Message> {
    let mut page = column![
        text("Connect to an sbt2 server").size(24),
        text_input("ws://host:8765 or wss://host", &form.url)
            .id(URL_INPUT)
            .on_input(Message::UrlChanged)
            .on_submit(Message::Connect),
        text_input("API token", &form.token)
            .id(TOKEN_INPUT)
            .secure(true)
            .on_input(Message::TokenChanged)
            .on_submit(Message::Connect),
        button("Connect")
            .on_press_maybe((*status != Status::Connecting).then_some(Message::Connect)),
    ]
    .spacing(12)
    .max_width(480);
    page = page.push(text(status.text()));
    for warning in warnings {
        page = page.push(text(warning));
    }
    container(page).center(Length::Fill).into()
}
