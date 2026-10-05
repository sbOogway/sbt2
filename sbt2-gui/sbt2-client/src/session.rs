use std::sync::Arc;

use tokio::sync::{mpsc, oneshot, watch};

use crate::{
    Backoff, ClientError, ServerAddress, Token,
    connection::{Command, Connection, Dial},
    dispatch::{Dispatcher, Reply},
    ids::RequestIds,
    protocol::{
        ClientMessage, GetMetrics, GetRun, ListRuns, RunFilter, RunSummary, Welcome,
        client_message, server_message::Body,
    },
    results::RunMetrics,
};

/// Whether the session has a working connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionState {
    Connected,
    /// The connection dropped; the session retries with a growing delay.
    Reconnecting,
    /// The session is closed, or the server refused the token on a retry.
    Disconnected,
}

/// Connects to a server.
#[derive(Debug, Clone)]
pub struct Client {
    address: ServerAddress,
    token: Token,
    backoff: Backoff,
}

impl Client {
    pub fn new(address: ServerAddress, token: Token) -> Self {
        let backoff = Backoff::default();
        Self {
            address,
            token,
            backoff,
        }
    }

    /// Sets the delays between attempts to reconnect.
    pub fn backoff(mut self, backoff: Backoff) -> Self {
        self.backoff = backoff;
        self
    }

    /// Opens the connection and shakes hands; the session is ready once this returns.
    pub async fn connect(self) -> Result<Session, ClientError> {
        let ids = Arc::new(RequestIds::default());
        let dial = Dial {
            address: self.address,
            token: self.token,
            backoff: self.backoff,
            ids: Arc::clone(&ids),
        };
        let (link, welcome) = dial.open().await?;
        let (commands, inbox) = mpsc::unbounded_channel();
        let (sender, state) = watch::channel(ConnectionState::Connected);
        let connection = Connection {
            inbox,
            state: sender,
            dial,
            dispatcher: Dispatcher::default(),
        };
        tokio::spawn(connection.run(link));
        Ok(Session {
            commands,
            ids,
            welcome: Arc::new(welcome),
            state,
        })
    }
}

/// A handle on a connected server; clones share the connection, which closes
/// when the last clone is dropped or `close` is called.
#[derive(Debug, Clone)]
pub struct Session {
    commands: mpsc::UnboundedSender<Command>,
    ids: Arc<RequestIds>,
    welcome: Arc<Welcome>,
    state: watch::Receiver<ConnectionState>,
}

impl Session {
    /// A session on no server: every request fails with `Disconnected`.
    #[cfg(feature = "test-support")]
    pub fn offline(welcome: Welcome) -> Self {
        let (commands, _) = mpsc::unbounded_channel();
        let (_, state) = watch::channel(ConnectionState::Connected);
        Self {
            commands,
            ids: Arc::default(),
            welcome: Arc::new(welcome),
            state,
        }
    }

    pub fn welcome(&self) -> &Welcome {
        &self.welcome
    }

    pub fn state(&self) -> ConnectionState {
        *self.state.borrow()
    }

    /// Changes of the connection state, from the current one on.
    pub fn states(&self) -> watch::Receiver<ConnectionState> {
        self.state.clone()
    }

    pub fn close(&self) {
        let _ = self.commands.send(Command::Close);
    }

    pub async fn list_runs(&self, filter: RunFilter) -> Result<Vec<RunSummary>, ClientError> {
        let filter = Some(filter);
        let chunks = self
            .request(client_message::Body::ListRuns(ListRuns { filter }))
            .await?;
        let mut runs = Vec::new();
        for chunk in chunks {
            match chunk {
                Body::RunList(list) => runs.extend(list.runs),
                other => return Err(unexpected(&other)),
            }
        }
        Ok(runs)
    }

    pub async fn get_run(&self, run_id: &str) -> Result<RunSummary, ClientError> {
        let run_id = run_id.to_owned();
        let chunks = self
            .request(client_message::Body::GetRun(GetRun { run_id }))
            .await?;
        match chunks.into_iter().next() {
            Some(Body::RunSummary(summary)) => Ok(*summary),
            Some(other) => Err(unexpected(&other)),
            None => Err(ClientError::Protocol("empty reply".to_owned())),
        }
    }

    pub async fn get_metrics(&self, run_id: &str) -> Result<RunMetrics, ClientError> {
        let run_id = run_id.to_owned();
        let chunks = self
            .request(client_message::Body::GetMetrics(GetMetrics { run_id }))
            .await?;
        let mut metrics = RunMetrics::default();
        for chunk in chunks {
            match chunk {
                Body::Metrics(part) => {
                    if metrics.currency.is_empty() {
                        metrics.currency = part.currency;
                    }
                    metrics.entries.extend(part.entries);
                }
                other => return Err(unexpected(&other)),
            }
        }
        Ok(metrics)
    }

    /// The pushes of one subscription, whose id the caller got from a reply.
    /// The stream ends when the connection drops; the caller subscribes again.
    pub fn subscribe(&self, subscription_id: u64) -> Subscription {
        let (stream, receiver) = mpsc::unbounded_channel();
        let _ = self.commands.send(Command::Subscribe {
            subscription_id,
            stream,
        });
        Subscription(receiver)
    }

    async fn request(&self, body: client_message::Body) -> Reply {
        let message = ClientMessage {
            request_id: self.ids.next(),
            body: Some(body),
        };
        let (reply, answer) = oneshot::channel();
        self.commands
            .send(Command::Request { message, reply })
            .map_err(|_| ClientError::Disconnected)?;
        answer.await.map_err(|_| ClientError::Disconnected)?
    }
}

/// The pushes of one subscription, in arrival order.
#[derive(Debug)]
pub struct Subscription(mpsc::UnboundedReceiver<Body>);

impl Subscription {
    /// The next push; `None` once the connection is gone.
    pub async fn next(&mut self) -> Option<Body> {
        self.0.recv().await
    }
}

fn unexpected(body: &Body) -> ClientError {
    ClientError::Protocol(format!("unexpected reply {body:?}"))
}
