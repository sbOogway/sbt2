use std::{fmt, path::PathBuf};

use iced::{
    Element, Length, Task,
    futures::stream,
    widget::{self, button, column, container, row, text, text_input},
};
use sbt2_client::{
    Client, ClientError, ConnectionState, ServerAddress, Session, Token, protocol::RunFilter,
};

use crate::{
    navigation::{self, Area},
    runs_table::{self, RunsTable},
    settings::{self, Settings},
    token_store::{Storage, TokenStore},
};

/// Where the app keeps what it remembers.
pub struct Environment {
    pub config_dir: PathBuf,
    pub tokens: TokenStore,
}

impl Environment {
    /// The XDG config folder and the OS keyring.
    pub fn system() -> Self {
        let config_dir = settings::config_dir();
        let tokens = TokenStore::system(&config_dir);
        Self { config_dir, tokens }
    }
}

#[derive(Debug, Clone)]
pub enum Message {
    UrlChanged(String),
    TokenChanged(String),
    Connect,
    Connected(Result<Session, ClientError>),
    Disconnect,
    StateChanged(ConnectionState),
    Show(Area),
    Runs(runs_table::Message),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Warning {
    NoKeyring,
    NotSaved(String),
}

impl fmt::Display for Warning {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoKeyring => formatter
                .write_str("No OS keyring: the token is kept in a file that only you can read."),
            Self::NotSaved(reason) => write!(formatter, "Could not save the connection: {reason}"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Status {
    Idle,
    Connecting,
    Failed(String),
}

#[derive(Debug, Default)]
struct Form {
    url: String,
    token: String,
}

struct Connected {
    session: Session,
    version: String,
    areas: Vec<Area>,
    area: Option<Area>,
    state: ConnectionState,
}

/// The connection screen until a server answers, then the app shell.
pub struct App {
    env: Environment,
    form: Form,
    status: Status,
    warnings: Vec<Warning>,
    connected: Option<Connected>,
    runs: RunsTable,
}

impl App {
    pub fn new(env: Environment) -> (Self, Task<Message>) {
        let url = Settings::load(&env.config_dir)
            .last_server
            .unwrap_or_default();
        let token = env.tokens.load(&url).unwrap_or_default();
        let app = Self {
            env,
            form: Form { url, token },
            status: Status::Idle,
            warnings: Vec::new(),
            connected: None,
            runs: RunsTable::default(),
        };
        (app, Task::none())
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::UrlChanged(url) => self.form.url = url,
            Message::TokenChanged(token) => self.form.token = token,
            Message::Connect => return self.connect(),
            Message::Connected(Ok(session)) => return self.enter(session),
            Message::Connected(Err(error)) => self.status = Status::Failed(error.to_string()),
            Message::Disconnect => self.leave(),
            Message::StateChanged(state) => return self.state_changed(state),
            Message::Show(area) => self.show(area),
            Message::Runs(message) => return self.update_runs(message),
        }
        Task::none()
    }

    pub fn view(&self) -> Element<'_, Message> {
        match &self.connected {
            Some(connected) => self.shell(connected),
            None => self.connection_screen(),
        }
    }

    fn connect(&mut self) -> Task<Message> {
        if self.status == Status::Connecting {
            return Task::none();
        }
        match ServerAddress::parse(&self.form.url) {
            Ok(address) => {
                self.status = Status::Connecting;
                let client = Client::new(address, Token::new(self.form.token.clone()));
                Task::perform(client.connect(), Message::Connected)
            }
            Err(error) => {
                self.status = Status::Failed(error.to_string());
                Task::none()
            }
        }
    }

    fn enter(&mut self, session: Session) -> Task<Message> {
        self.status = Status::Idle;
        self.remember();
        let areas = navigation::areas(session.welcome());
        let connected = Connected {
            version: session.welcome().server_version.clone(),
            area: areas.first().copied(),
            areas,
            state: session.state(),
            session,
        };
        let states = watch_states(&connected.session);
        self.connected = Some(connected);
        self.runs = RunsTable::default();
        Task::batch([states, self.load_runs()])
    }

    fn leave(&mut self) {
        if let Some(connected) = self.connected.take() {
            connected.session.close();
        }
        self.status = Status::Idle;
    }

    fn state_changed(&mut self, state: ConnectionState) -> Task<Message> {
        let Some(connected) = &mut self.connected else {
            return Task::none();
        };
        let recovered =
            connected.state == ConnectionState::Reconnecting && state == ConnectionState::Connected;
        connected.state = state;
        if recovered {
            self.load_runs()
        } else {
            Task::none()
        }
    }

    fn show(&mut self, area: Area) {
        if let Some(connected) = &mut self.connected {
            connected.area = Some(area);
        }
    }

    fn update_runs(&mut self, message: runs_table::Message) -> Task<Message> {
        if self.runs.update(message) {
            self.load_runs()
        } else {
            Task::none()
        }
    }

    fn load_runs(&self) -> Task<Message> {
        let Some(connected) = &self.connected else {
            return Task::none();
        };
        if !connected.areas.contains(&Area::Runs) {
            return Task::none();
        }
        let session = connected.session.clone();
        Task::perform(
            async move { session.list_runs(RunFilter::default()).await },
            |runs| Message::Runs(runs_table::Message::Loaded(runs)),
        )
    }

    fn remember(&mut self) {
        self.warnings.clear();
        let settings = Settings {
            last_server: Some(self.form.url.clone()),
        };
        if let Err(error) = settings.save(&self.env.config_dir) {
            self.warnings.push(Warning::NotSaved(error.to_string()));
        }
        match self.env.tokens.save(&self.form.url, &self.form.token) {
            Ok(Storage::Keyring) => {}
            Ok(Storage::File) => self.warnings.push(Warning::NoKeyring),
            Err(error) => self.warnings.push(Warning::NotSaved(error.to_string())),
        }
    }

    fn connection_screen(&self) -> Element<'_, Message> {
        let mut form = column![
            text("Connect to an sbt2 server").size(24),
            text_input("ws://host:8765 or wss://host", &self.form.url)
                .id(URL_INPUT)
                .on_input(Message::UrlChanged)
                .on_submit(Message::Connect),
            text_input("API token", &self.form.token)
                .id(TOKEN_INPUT)
                .secure(true)
                .on_input(Message::TokenChanged)
                .on_submit(Message::Connect),
            button("Connect")
                .on_press_maybe((self.status != Status::Connecting).then_some(Message::Connect)),
        ]
        .spacing(12)
        .max_width(480);
        form = form.push(text(self.status_text()));
        for warning in &self.warnings {
            form = form.push(text(warning.to_string()));
        }
        container(form).center(Length::Fill).into()
    }

    fn status_text(&self) -> String {
        match &self.status {
            Status::Idle => String::new(),
            Status::Connecting => "Connecting...".to_owned(),
            Status::Failed(error) => format!("Connection failed: {error}"),
        }
    }

    fn shell<'a>(&'a self, connected: &'a Connected) -> Element<'a, Message> {
        let navigation = connected.areas.iter().map(|area| {
            let label = button(text(area.title()));
            let selected = connected.area == Some(*area);
            label
                .on_press_maybe((!selected).then_some(Message::Show(*area)))
                .into()
        });
        let bar = row(navigation)
            .push(widget::space::horizontal())
            .push(text(format!(
                "Server {}: {}",
                connected.version,
                state_text(connected.state)
            )))
            .push(button("Disconnect").on_press(Message::Disconnect))
            .spacing(12);
        let mut page = column![bar].spacing(12).padding(12);
        for warning in &self.warnings {
            page = page.push(text(warning.to_string()));
        }
        page.push(self.area(connected)).into()
    }

    fn area<'a>(&'a self, connected: &Connected) -> Element<'a, Message> {
        match connected.area {
            Some(Area::Runs) => self.runs.view().map(Message::Runs),
            Some(Area::Config) => text("Config comes in a later version.").into(),
            None => text("The server offers nothing this GUI can show.").into(),
        }
    }
}

const URL_INPUT: &str = "server-url";
const TOKEN_INPUT: &str = "server-token";

fn state_text(state: ConnectionState) -> &'static str {
    match state {
        ConnectionState::Connected => "connected",
        ConnectionState::Reconnecting => "reconnecting",
        ConnectionState::Disconnected => "disconnected",
    }
}

fn watch_states(session: &Session) -> Task<Message> {
    let states = session.states();
    let changes = stream::unfold(states, |mut states| async {
        states.changed().await.ok()?;
        let state = *states.borrow_and_update();
        Some((state, states))
    });
    Task::run(changes, Message::StateChanged)
}

#[cfg(test)]
mod tests {
    use std::{fs, os::unix::fs::PermissionsExt};

    use sbt2_client::protocol::{Capability, Welcome};
    use tempfile::TempDir;

    use super::*;

    fn app_in(folder: &TempDir, tokens: TokenStore) -> App {
        let env = Environment {
            config_dir: folder.path().to_path_buf(),
            tokens,
        };
        App::new(env).0
    }

    fn offline_session(capabilities: &[Capability]) -> Session {
        Session::offline(Welcome {
            server_version: "9.9.9".to_owned(),
            capabilities: capabilities.iter().map(|each| *each as i32).collect(),
        })
    }

    fn filled(app: &mut App, url: &str) {
        let _ = app.update(Message::UrlChanged(url.to_owned()));
        let _ = app.update(Message::TokenChanged("s3cret".to_owned()));
    }

    #[test]
    fn connecting_goes_through_connecting_and_connected_and_shows_the_server_version() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");
        assert_eq!(app.status, Status::Idle);

        let _ = app.update(Message::Connect);
        assert_eq!(app.status, Status::Connecting);
        assert!(app.connected.is_none());

        let session = offline_session(&[Capability::Results]);
        let _ = app.update(Message::Connected(Ok(session)));
        assert_eq!(app.status, Status::Idle);
        let connected = app.connected.as_ref().unwrap();
        assert_eq!(connected.version, "9.9.9");
        assert_eq!(connected.areas, [Area::Runs]);
        assert_eq!(connected.state, ConnectionState::Connected);
    }

    #[test]
    fn a_failed_connection_shows_its_error_and_stays_on_the_connection_screen() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "http://not-a-websocket");

        let _ = app.update(Message::Connect);
        assert!(matches!(&app.status, Status::Failed(error) if error.contains("ws://")));

        filled(&mut app, "ws://127.0.0.1:1");
        let _ = app.update(Message::Connect);
        let _ = app.update(Message::Connected(Err(ClientError::Unauthorized)));

        assert_eq!(
            app.status,
            Status::Failed("the server refused the token".to_owned())
        );
        assert!(app.connected.is_none());
    }

    #[test]
    fn without_a_keyring_the_token_goes_to_a_0600_file_and_a_warning_is_shown() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");

        let _ = app.update(Message::Connected(Ok(offline_session(&[]))));

        let file = folder.path().join("tokens.toml");
        let mode = fs::metadata(file).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o600);
        assert_eq!(app.warnings, [Warning::NoKeyring]);
    }

    #[test]
    fn the_last_server_and_its_token_prefill_the_next_start() {
        let folder = TempDir::new().unwrap();
        let mut first = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut first, "ws://127.0.0.1:1");
        let _ = first.update(Message::Connected(Ok(offline_session(&[]))));

        let second = app_in(&folder, TokenStore::new(None, folder.path()));

        assert_eq!(second.form.url, "ws://127.0.0.1:1");
        assert_eq!(second.form.token, "s3cret");
    }

    #[test]
    fn disconnecting_returns_to_the_connection_screen() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");
        let _ = app.update(Message::Connected(Ok(offline_session(&[]))));

        let _ = app.update(Message::Disconnect);

        assert!(app.connected.is_none());
        assert_eq!(app.status, Status::Idle);
    }
}
