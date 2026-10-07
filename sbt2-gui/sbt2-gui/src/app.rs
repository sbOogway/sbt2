use std::{fmt, path::PathBuf};

use iced::{
    Element, Task,
    futures::stream,
    widget::{self, button, column, row, text},
};
use sbt2_client::{
    Client, ClientError, ConnectionState, ServerAddress, Session, Token, VERSION,
    protocol::RunFilter,
};

use crate::{
    config::{self, Settings, Storage, TokenStore},
    screens::{
        connection::{self, Form, Status},
        navigation::{self, Area},
        run_detail::{self, Load, RunDetail},
        runs::{self, RunsTable},
    },
};

/// Where the app keeps what it remembers.
pub struct Environment {
    pub config_dir: PathBuf,
    pub tokens: TokenStore,
}

impl Environment {
    /// The XDG config folder and the OS keyring.
    pub fn system() -> Self {
        let config_dir = config::config_dir();
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
    Runs(runs::Message),
    Detail(run_detail::Message),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Warning {
    NoKeyring,
    NotSaved(String),
    VersionMismatch { server: String },
}

impl fmt::Display for Warning {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoKeyring => formatter
                .write_str("No OS keyring: the token is kept in a file that only you can read."),
            Self::NotSaved(reason) => write!(formatter, "Could not save the connection: {reason}"),
            Self::VersionMismatch { server } => write!(
                formatter,
                "The server is version {server} but this GUI is version {}.",
                VERSION
            ),
        }
    }
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
    detail: RunDetail,
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
            detail: RunDetail::default(),
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
            Message::Detail(message) => return self.update_detail(message),
        }
        Task::none()
    }

    pub fn view(&self) -> Element<'_, Message> {
        match &self.connected {
            Some(connected) => self.shell(connected),
            None => connection::view(
                &self.form,
                &self.status,
                self.warnings.iter().map(ToString::to_string),
            ),
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
        self.check_version(&session);
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
        self.detail = RunDetail::default();
        Task::batch([states, self.load_runs()])
    }

    fn leave(&mut self) {
        if let Some(connected) = self.connected.take() {
            connected.session.close();
        }
        self.detail = RunDetail::default();
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

    fn update_runs(&mut self, message: runs::Message) -> Task<Message> {
        if let runs::Message::Open(run_id) = &message {
            let loads = self.detail.open(run_id);
            return self.start(loads);
        }
        if self.runs.update(message) {
            self.load_runs()
        } else {
            Task::none()
        }
    }

    fn update_detail(&mut self, message: run_detail::Message) -> Task<Message> {
        let back = matches!(message, run_detail::Message::Back);
        let loads = self.detail.update(message);
        let loading = self.start(loads);
        if back {
            Task::batch([loading, self.runs.restore_scroll().map(Message::Runs)])
        } else {
            loading
        }
    }

    fn start(&self, loads: Vec<Load>) -> Task<Message> {
        let (Some(connected), Some(run_id)) = (&self.connected, self.detail.run_id()) else {
            return Task::none();
        };
        let tasks = loads.into_iter().map(|load| {
            let session = connected.session.clone();
            let run_id = run_id.to_owned();
            Task::perform(
                async move {
                    let loaded = load.fetch(&session, &run_id).await;
                    run_detail::Message::Loaded(run_id, loaded)
                },
                Message::Detail,
            )
        });
        Task::batch(tasks)
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
            |runs| Message::Runs(runs::Message::Loaded(runs)),
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

    fn check_version(&mut self, session: &Session) {
        let server = &session.welcome().server_version;
        if server != VERSION {
            self.warnings.push(Warning::VersionMismatch {
                server: server.clone(),
            });
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
                "GUI {VERSION}, server {}: {}",
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
            Some(Area::Runs) if self.detail.is_open() => self.detail.view().map(Message::Detail),
            Some(Area::Runs) => self.runs.view().map(Message::Runs),
            Some(Area::Config) => text("Config comes in a later version.").into(),
            None => text("The server offers nothing this GUI can show.").into(),
        }
    }
}

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
    use std::fs;

    use sbt2_client::protocol::{Capability, HeadlineMetrics, RunSummary, Welcome};
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
        offline_session_of(VERSION, capabilities)
    }

    fn offline_session_of(server_version: &str, capabilities: &[Capability]) -> Session {
        Session::offline(Welcome {
            server_version: server_version.to_owned(),
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
        assert_eq!(connected.version, VERSION);
        assert_eq!(connected.areas, [Area::Runs]);
        assert_eq!(connected.state, ConnectionState::Connected);
    }

    #[test]
    fn a_server_with_another_version_shows_a_version_warning() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");

        let _ = app.update(Message::Connected(Ok(offline_session_of("0.0.1", &[]))));

        assert!(app.connected.is_some());
        let warning = Warning::VersionMismatch {
            server: "0.0.1".to_owned(),
        };
        assert!(app.warnings.contains(&warning));
        let text = warning.to_string();
        assert!(text.contains("0.0.1") && text.contains(VERSION));
    }

    #[test]
    fn a_server_with_the_same_version_shows_no_warning() {
        let folder = TempDir::new().unwrap();
        let mut app = app_in(&folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");

        let _ = app.update(Message::Connected(Ok(offline_session_of(VERSION, &[]))));

        assert!(
            !app.warnings
                .iter()
                .any(|warning| matches!(warning, Warning::VersionMismatch { .. }))
        );
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

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            let file = folder.path().join("tokens.toml");
            let mode = fs::metadata(file).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600);
        }
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

    fn connected_app(folder: &TempDir) -> App {
        let mut app = app_in(folder, TokenStore::new(None, folder.path()));
        filled(&mut app, "ws://127.0.0.1:1");
        let session = offline_session(&[Capability::Results]);
        let _ = app.update(Message::Connected(Ok(session)));
        app
    }

    fn run(id: &str, trades: u64) -> RunSummary {
        RunSummary {
            run_id: id.to_owned(),
            headline: Some(HeadlineMetrics {
                trade_count: trades,
                ..HeadlineMetrics::default()
            }),
            ..RunSummary::default()
        }
    }

    fn order(app: &App) -> Vec<&str> {
        app.runs
            .sorted()
            .iter()
            .map(|run| run.run_id.as_str())
            .collect()
    }

    #[test]
    fn opening_a_run_shows_its_detail_and_back_returns_to_the_table_with_its_sort() {
        let folder = TempDir::new().unwrap();
        let mut app = connected_app(&folder);
        let runs = vec![run("a", 3), run("b", 1)];
        let _ = app.update(Message::Runs(runs::Message::Loaded(Ok(runs))));
        let _ = app.update(Message::Runs(runs::Message::Sort(runs::Column::Trades)));

        let _ = app.update(Message::Runs(runs::Message::Open("a".to_owned())));
        assert_eq!(app.detail.run_id(), Some("a"));

        let _ = app.update(Message::Detail(run_detail::Message::Back));
        assert!(!app.detail.is_open());
        assert_eq!(order(&app), ["b", "a"]);
    }

    #[test]
    fn a_disconnect_clears_the_cached_runs() {
        let folder = TempDir::new().unwrap();
        let mut app = connected_app(&folder);
        let _ = app.update(Message::Runs(runs::Message::Open("a".to_owned())));
        let _ = app.update(Message::Detail(run_detail::Message::Back));
        assert_eq!(app.detail.open("a"), []);

        let _ = app.update(Message::Disconnect);
        let session = offline_session(&[Capability::Results]);
        let _ = app.update(Message::Connected(Ok(session)));

        assert_eq!(app.detail.open("a"), [Load::Summary, Load::Metrics]);
    }
}
