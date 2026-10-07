use std::collections::HashMap;

use tokio::sync::{mpsc, oneshot};

use crate::{
    ClientError,
    protocol::{ServerMessage, server_message::Body},
};

/// The chunks of one complete response, in index order.
pub(crate) type Reply = Result<Vec<Body>, ClientError>;

/// Matches each server message to the request or subscription it belongs to.
#[derive(Default)]
pub(crate) struct Dispatcher {
    pending: HashMap<u64, Pending>,
    subscriptions: HashMap<u64, mpsc::UnboundedSender<Body>>,
}

struct Pending {
    reply: oneshot::Sender<Reply>,
    chunks: Vec<Body>,
}

impl Dispatcher {
    pub(crate) fn expect(&mut self, request_id: u64, reply: oneshot::Sender<Reply>) {
        let chunks = Vec::new();
        self.pending.insert(request_id, Pending { reply, chunks });
    }

    pub(crate) fn subscribe(&mut self, subscription_id: u64, stream: mpsc::UnboundedSender<Body>) {
        self.subscriptions.insert(subscription_id, stream);
    }

    pub(crate) fn receive(&mut self, message: ServerMessage) {
        let Some(body) = message.body else {
            tracing::warn!("dropped a server message without a body");
            return;
        };
        if message.subscription_id != 0 {
            self.push(message.subscription_id, body);
        } else {
            self.answer(message.request_id, body);
        }
    }

    /// Fails every outstanding request and ends every subscription's stream.
    pub(crate) fn fail_all(&mut self, error: &ClientError) {
        self.subscriptions.clear();
        for (_, pending) in self.pending.drain() {
            let _ = pending.reply.send(Err(error.clone()));
        }
    }

    fn push(&mut self, subscription_id: u64, body: Body) {
        match self.subscriptions.get(&subscription_id) {
            Some(stream) if stream.send(body).is_ok() => {}
            Some(_) => {
                self.subscriptions.remove(&subscription_id);
            }
            None => tracing::warn!("dropped a push for the unknown subscription {subscription_id}"),
        }
    }

    fn answer(&mut self, request_id: u64, body: Body) {
        let Some(pending) = self.pending.get_mut(&request_id) else {
            tracing::warn!("dropped a reply to the unknown request {request_id}");
            return;
        };
        if let Body::Error(error) = body {
            let code = error.code();
            let message = error.message;
            self.finish(request_id, Err(ClientError::Server { code, message }));
            return;
        }
        let last = is_last(&body);
        pending.chunks.push(body);
        if last {
            self.finish_chunks(request_id);
        }
    }

    fn finish_chunks(&mut self, request_id: u64) {
        let Some(pending) = self.pending.get_mut(&request_id) else {
            return;
        };
        let mut chunks = std::mem::take(&mut pending.chunks);
        chunks.sort_by_key(chunk_index);
        let reply = if has_every_index(&chunks) {
            Ok(chunks)
        } else {
            Err(ClientError::Protocol(
                "the reply has a gap or a duplicate in its chunk indexes".to_owned(),
            ))
        };
        self.finish(request_id, reply);
    }

    fn finish(&mut self, request_id: u64, reply: Reply) {
        if let Some(pending) = self.pending.remove(&request_id) {
            let _ = pending.reply.send(reply);
        }
    }
}

fn has_every_index(sorted: &[Body]) -> bool {
    sorted
        .iter()
        .zip(0..)
        .all(|(chunk, expected)| chunk_index(chunk) == expected)
}

fn is_last(body: &Body) -> bool {
    match body {
        Body::RunList(chunk) => chunk.last,
        Body::Metrics(chunk) => chunk.last,
        Body::Series(chunk) => chunk.last,
        Body::Panel(chunk) => chunk.last,
        Body::Tearsheet(chunk) => chunk.last,
        _ => true,
    }
}

fn chunk_index(body: &Body) -> u64 {
    match body {
        Body::RunList(chunk) => chunk.index,
        Body::Metrics(chunk) => chunk.index,
        Body::Series(chunk) => chunk.index,
        Body::Panel(chunk) => chunk.index,
        Body::Tearsheet(chunk) => chunk.index,
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use tokio::sync::oneshot::error::TryRecvError;

    use super::*;
    use crate::protocol::{Error, ErrorCode, Panel, RunList, RunSummary, Series};

    fn run_chunk(request_id: u64, index: u64, last: bool, run_ids: &[&str]) -> ServerMessage {
        let runs = run_ids
            .iter()
            .map(|id| RunSummary {
                run_id: (*id).to_owned(),
                ..RunSummary::default()
            })
            .collect();
        ServerMessage {
            request_id,
            body: Some(Body::RunList(RunList { index, last, runs })),
            ..ServerMessage::default()
        }
    }

    fn panel_chunk(request_id: u64, index: u64, last: bool) -> ServerMessage {
        ServerMessage {
            request_id,
            body: Some(Body::Panel(Panel {
                index,
                last,
                data: vec![index as u8],
            })),
            ..ServerMessage::default()
        }
    }

    fn panel_indexes(chunks: Vec<Body>) -> Vec<u64> {
        chunks
            .into_iter()
            .map(|chunk| match chunk {
                Body::Panel(panel) => panel.index,
                other => panic!("not a panel: {other:?}"),
            })
            .collect()
    }

    fn error_reply(request_id: u64, code: ErrorCode, message: &str) -> ServerMessage {
        ServerMessage {
            request_id,
            body: Some(Body::Error(Error {
                code: code.into(),
                message: message.to_owned(),
                ..Error::default()
            })),
            ..ServerMessage::default()
        }
    }

    fn series_push(subscription_id: u64, data: &[u8]) -> ServerMessage {
        ServerMessage {
            subscription_id,
            body: Some(Body::Series(Series {
                data: data.to_vec(),
                ..Series::default()
            })),
            ..ServerMessage::default()
        }
    }

    fn run_ids(chunks: Vec<Body>) -> Vec<String> {
        chunks
            .into_iter()
            .flat_map(|chunk| match chunk {
                Body::RunList(list) => list.runs,
                other => panic!("not a run list: {other:?}"),
            })
            .map(|run| run.run_id)
            .collect()
    }

    #[test]
    fn chunks_are_joined_in_index_order_until_the_last() {
        let mut dispatcher = Dispatcher::default();
        let (sender, mut reply) = oneshot::channel();
        dispatcher.expect(7, sender);

        dispatcher.receive(run_chunk(7, 1, false, &["b"]));
        dispatcher.receive(run_chunk(7, 0, false, &["a"]));
        assert_eq!(reply.try_recv().unwrap_err(), TryRecvError::Empty);

        dispatcher.receive(run_chunk(7, 2, true, &["c", "d"]));
        let chunks = reply.try_recv().unwrap().unwrap();
        assert_eq!(run_ids(chunks), ["a", "b", "c", "d"]);
    }

    #[test]
    fn panel_chunks_are_joined_in_index_order_until_the_last() {
        let mut dispatcher = Dispatcher::default();
        let (sender, mut reply) = oneshot::channel();
        dispatcher.expect(7, sender);

        dispatcher.receive(panel_chunk(7, 1, false));
        dispatcher.receive(panel_chunk(7, 0, false));
        assert_eq!(reply.try_recv().unwrap_err(), TryRecvError::Empty);

        dispatcher.receive(panel_chunk(7, 2, true));
        let chunks = reply.try_recv().unwrap().unwrap();
        assert_eq!(panel_indexes(chunks), [0, 1, 2]);
    }

    #[test]
    fn a_gap_in_the_chunk_indexes_is_a_protocol_error() {
        let mut dispatcher = Dispatcher::default();
        let (sender, mut reply) = oneshot::channel();
        dispatcher.expect(7, sender);

        dispatcher.receive(panel_chunk(7, 0, false));
        dispatcher.receive(panel_chunk(7, 2, true));

        assert!(matches!(
            reply.try_recv().unwrap(),
            Err(ClientError::Protocol(_))
        ));
    }

    #[test]
    fn an_error_reply_ends_the_request_with_its_code_and_message() {
        let mut dispatcher = Dispatcher::default();
        let (sender, mut reply) = oneshot::channel();
        dispatcher.expect(7, sender);

        dispatcher.receive(run_chunk(7, 0, false, &["a"]));
        dispatcher.receive(error_reply(7, ErrorCode::NotFound, "no such run"));

        assert_eq!(
            reply.try_recv().unwrap(),
            Err(ClientError::Server {
                code: ErrorCode::NotFound,
                message: "no such run".to_owned(),
            })
        );
        dispatcher.receive(run_chunk(7, 1, true, &["b"]));
    }

    #[test]
    fn a_push_goes_to_the_stream_of_its_subscription() {
        let mut dispatcher = Dispatcher::default();
        let (first_sender, mut first) = mpsc::unbounded_channel();
        let (second_sender, mut second) = mpsc::unbounded_channel();
        dispatcher.subscribe(1, first_sender);
        dispatcher.subscribe(2, second_sender);

        dispatcher.receive(series_push(2, b"two"));
        dispatcher.receive(series_push(1, b"one"));
        dispatcher.receive(series_push(9, b"nobody"));

        let Body::Series(one) = first.try_recv().unwrap() else {
            panic!("not a series")
        };
        let Body::Series(two) = second.try_recv().unwrap() else {
            panic!("not a series")
        };
        assert_eq!((one.data, two.data), (b"one".to_vec(), b"two".to_vec()));
        assert!(first.try_recv().is_err() && second.try_recv().is_err());
    }

    #[test]
    fn failing_all_ends_every_outstanding_request() {
        let mut dispatcher = Dispatcher::default();
        let (sender, mut reply) = oneshot::channel();
        dispatcher.expect(3, sender);

        dispatcher.fail_all(&ClientError::Disconnected);

        assert_eq!(reply.try_recv().unwrap(), Err(ClientError::Disconnected));
    }
}
