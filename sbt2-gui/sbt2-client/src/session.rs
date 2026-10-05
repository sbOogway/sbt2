use std::sync::Arc;

use tokio::sync::{mpsc, oneshot, watch};

use crate::{
    ClientError, ServerAddress, Token,
    dispatch::{Dispatcher, Reply},
    ids::RequestIds,
    protocol::{
        ClientMessage, Hello, RunFilter, RunSummary, ServerMessage, Welcome, client_message,
        server_message::Body,
    },
    transport::Link,
};

/// Whether the session has a working connection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionState {
    Connected,
    Disconnected,
}

/// Connects to a server.
#[derive(Debug, Clone)]
pub struct Client {
    address: ServerAddress,
    token: Token,
}

impl Client {
    pub fn new(address: ServerAddress, token: Token) -> Self {
        Self { address, token }
    }

    /// Opens the connection and shakes hands; the session is ready once this returns.
    pub async fn connect(self) -> Result<Session, ClientError> {
        let ids = Arc::new(RequestIds::default());
        let mut link = Link::open(&self.address, &self.token).await?;
        let welcome = greet(&mut link, &ids).await?;
        let (commands, inbox) = mpsc::unbounded_channel();
        let (state_sender, state) = watch::channel(ConnectionState::Connected);
        let connection = Connection {
            inbox,
            state: state_sender,
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
    pub fn welcome(&self) -> &Welcome {
        &self.welcome
    }

    pub fn state(&self) -> ConnectionState {
        *self.state.borrow()
    }

    pub fn states(&self) -> watch::Receiver<ConnectionState> {
        self.state.clone()
    }

    pub fn close(&self) {
        let _ = self.commands.send(Command::Close);
    }

    pub async fn list_runs(&self, filter: RunFilter) -> Result<Vec<RunSummary>, ClientError> {
        let body = client_message::Body::ListRuns(crate::protocol::ListRuns {
            filter: Some(filter),
        });
        let chunks = self.request(body).await?;
        let mut runs = Vec::new();
        for chunk in chunks {
            match chunk {
                Body::RunList(list) => runs.extend(list.runs),
                other => return Err(unexpected(&other)),
            }
        }
        Ok(runs)
    }

    /// The pushes of one subscription; the caller got its id from a reply.
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

enum Command {
    Request {
        message: ClientMessage,
        reply: oneshot::Sender<Reply>,
    },
    Subscribe {
        subscription_id: u64,
        stream: mpsc::UnboundedSender<Body>,
    },
    Close,
}

/// The task that owns the link: it sends requests and sorts the replies.
struct Connection {
    inbox: mpsc::UnboundedReceiver<Command>,
    state: watch::Sender<ConnectionState>,
    dispatcher: Dispatcher,
}

impl Connection {
    async fn run(mut self, mut link: Link) {
        let error = self.serve(&mut link).await;
        self.dispatcher.fail_all(&error);
        let _ = self.state.send(ConnectionState::Disconnected);
    }

    async fn serve(&mut self, link: &mut Link) -> ClientError {
        loop {
            tokio::select! {
                command = self.inbox.recv() => match command {
                    None | Some(Command::Close) => return ClientError::Disconnected,
                    Some(command) => {
                        if let Err(error) = self.start(command, link).await {
                            return error;
                        }
                    }
                },
                message = link.receive() => match message {
                    Ok(message) => self.dispatcher.receive(message),
                    Err(error) => return error,
                },
            }
        }
    }

    async fn start(&mut self, command: Command, link: &mut Link) -> Result<(), ClientError> {
        match command {
            Command::Request { message, reply } => {
                self.dispatcher.expect(message.request_id, reply);
                link.send(&message).await
            }
            Command::Subscribe {
                subscription_id,
                stream,
            } => {
                self.dispatcher.subscribe(subscription_id, stream);
                Ok(())
            }
            Command::Close => Ok(()),
        }
    }
}

async fn greet(link: &mut Link, ids: &RequestIds) -> Result<Welcome, ClientError> {
    let request_id = ids.next();
    let hello = Hello {
        client_version: env!("CARGO_PKG_VERSION").to_owned(),
    };
    let message = ClientMessage {
        request_id,
        body: Some(client_message::Body::Hello(hello)),
    };
    link.send(&message).await?;
    loop {
        let reply = link.receive().await?;
        if reply.request_id == request_id {
            return welcome_of(reply);
        }
    }
}

fn welcome_of(reply: ServerMessage) -> Result<Welcome, ClientError> {
    match reply.body {
        Some(Body::Welcome(welcome)) => Ok(welcome),
        Some(Body::Error(error)) => Err(ClientError::Server {
            code: error.code(),
            message: error.message,
        }),
        other => Err(ClientError::Protocol(format!(
            "expected Welcome, got {other:?}"
        ))),
    }
}

fn unexpected(body: &Body) -> ClientError {
    ClientError::Protocol(format!("unexpected reply {body:?}"))
}
