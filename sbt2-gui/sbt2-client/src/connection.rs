use std::{sync::Arc, time::Duration};

use tokio::sync::{mpsc, oneshot, watch};

use crate::{
    Backoff, ClientError, ConnectionState, ServerAddress, Token,
    dispatch::{Dispatcher, Reply},
    ids::RequestIds,
    protocol::{
        ClientMessage, Hello, ServerMessage, Welcome, client_message, server_message::Body,
    },
    transport::Link,
};

pub(crate) enum Command {
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

/// Where and how to open a connection, for the first time and again after a drop.
pub(crate) struct Dial {
    pub(crate) address: ServerAddress,
    pub(crate) token: Token,
    pub(crate) backoff: Backoff,
    pub(crate) ids: Arc<RequestIds>,
}

impl Dial {
    /// Opens a link and shakes hands on it.
    pub(crate) async fn open(&self) -> Result<(Link, Welcome), ClientError> {
        let mut link = Link::open(&self.address, &self.token).await?;
        let welcome = self.greet(&mut link).await?;
        Ok((link, welcome))
    }

    async fn greet(&self, link: &mut Link) -> Result<Welcome, ClientError> {
        let request_id = self.ids.next();
        let hello = Hello {
            client_version: env!("CARGO_PKG_VERSION").to_owned(),
        };
        let body = client_message::Body::Hello(hello);
        let message = ClientMessage {
            request_id,
            body: Some(body),
        };
        link.send(&message).await?;
        loop {
            let reply = link.receive().await?;
            if reply.request_id == request_id {
                return welcome_of(reply);
            }
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

enum Ended {
    Closed,
    Dropped(ClientError),
}

/// The task that owns the link: it sends requests, sorts the replies and
/// reconnects when the link drops.
pub(crate) struct Connection {
    pub(crate) inbox: mpsc::UnboundedReceiver<Command>,
    pub(crate) state: watch::Sender<ConnectionState>,
    pub(crate) dial: Dial,
    pub(crate) dispatcher: Dispatcher,
}

impl Connection {
    pub(crate) async fn run(mut self, mut link: Link) {
        while let Ended::Dropped(error) = self.serve(&mut link).await {
            self.dispatcher.fail_all(&error);
            self.state.send_replace(ConnectionState::Reconnecting);
            let Some(next) = self.reconnect().await else {
                break;
            };
            link = next;
            self.state.send_replace(ConnectionState::Connected);
        }
        self.dispatcher.fail_all(&ClientError::Disconnected);
        self.state.send_replace(ConnectionState::Disconnected);
    }

    async fn serve(&mut self, link: &mut Link) -> Ended {
        loop {
            tokio::select! {
                command = self.inbox.recv() => match command {
                    None | Some(Command::Close) => return Ended::Closed,
                    Some(command) => {
                        if let Err(error) = self.start(command, link).await {
                            return Ended::Dropped(error);
                        }
                    }
                },
                message = link.receive() => match message {
                    Ok(message) => self.dispatcher.receive(message),
                    Err(error) => return Ended::Dropped(error),
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

    /// A new link, or `None` when the session is closed or the token refused.
    async fn reconnect(&mut self) -> Option<Link> {
        let mut failures = 0;
        loop {
            if !self.wait_refusing(self.dial.backoff.delay(failures)).await {
                return None;
            }
            match self.dial.open().await {
                Ok((link, _)) => return Some(link),
                Err(ClientError::Unauthorized) => return None,
                Err(error) => {
                    tracing::warn!("reconnect failed: {error}");
                    failures += 1;
                }
            }
        }
    }

    /// Waits, failing the requests that come meanwhile; `false` when closed.
    async fn wait_refusing(&mut self, delay: Duration) -> bool {
        let timer = tokio::time::sleep(delay);
        tokio::pin!(timer);
        loop {
            tokio::select! {
                () = &mut timer => return true,
                command = self.inbox.recv() => match command {
                    None | Some(Command::Close) => return false,
                    Some(Command::Request { reply, .. }) => {
                        let _ = reply.send(Err(ClientError::Disconnected));
                    }
                    Some(Command::Subscribe { .. }) => {}
                },
            }
        }
    }
}
