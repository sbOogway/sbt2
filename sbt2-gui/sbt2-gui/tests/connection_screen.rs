use iced::widget::Id;
use iced_test::simulator;
use sbt2_gui::{App, Environment, Message, TokenStore};
use tempfile::TempDir;

#[test]
fn the_connection_screen_connects_with_the_entered_url_and_token() {
    let folder = TempDir::new().unwrap();
    let env = Environment {
        config_dir: folder.path().to_path_buf(),
        tokens: TokenStore::new(None, folder.path()),
    };
    let (app, _) = App::new(env);

    let mut ui = simulator(app.view());
    ui.click(Id::new("server-url")).unwrap();
    ui.typewrite("ws://127.0.0.1:9");
    ui.click(Id::new("server-token")).unwrap();
    ui.typewrite("s3cret");
    ui.click("Connect").unwrap();
    let messages: Vec<Message> = ui.into_messages().collect();

    let url = messages.iter().rev().find_map(|message| match message {
        Message::UrlChanged(url) => Some(url.as_str()),
        _ => None,
    });
    let token = messages.iter().rev().find_map(|message| match message {
        Message::TokenChanged(token) => Some(token.as_str()),
        _ => None,
    });
    assert_eq!(url, Some("ws://127.0.0.1:9"));
    assert_eq!(token, Some("s3cret"));
    assert!(matches!(messages.last(), Some(Message::Connect)));
}
