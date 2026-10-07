use std::time::Duration;

use std::sync::Arc;

use arrow_array::TimestampNanosecondArray;
use arrow_array::{ArrayRef, Float64Array, Int64Array, RecordBatch, StringArray};
use arrow_ipc::writer::StreamWriter;
use arrow_schema::{Field, Schema};
use sbt2_client::{
    Cell, Client, ClientError, Point, ServerAddress, Session, Token,
    protocol::{
        BenchmarkKind, BenchmarkSelection, Error, ErrorCode, Metric, Metrics, Panel, PanelKind,
        RunSummary, Series, SeriesKind, ServerMessage, client_message, server_message::Body,
    },
};
use tokio::time::timeout;

use crate::support::{TOKEN, reply, serve};

async fn connected(address: ServerAddress) -> Session {
    timeout(
        Duration::from_secs(5),
        Client::new(address, Token::new(TOKEN)).connect(),
    )
    .await
    .expect("connect timed out")
    .expect("connect failed")
}

fn metrics_chunk(request_id: u64, index: u64, last: bool, names: &[&str]) -> ServerMessage {
    let entries = names
        .iter()
        .map(|name| Metric {
            name: (*name).to_owned(),
            value: Some("1.5".to_owned()),
            ..Metric::default()
        })
        .collect();
    let currency = "USD".to_owned();
    let chunk = Metrics {
        index,
        last,
        currency,
        entries,
    };
    reply(request_id, Body::Metrics(chunk))
}

fn error_reply(request_id: u64, code: ErrorCode, message: &str) -> ServerMessage {
    let error = Error {
        code: code.into(),
        message: message.to_owned(),
        ..Error::default()
    };
    reply(request_id, Body::Error(error))
}

fn arrow_stream(columns: Vec<(&str, ArrayRef)>) -> Vec<u8> {
    let fields: Vec<_> = columns
        .iter()
        .map(|(name, array)| Field::new(*name, array.data_type().clone(), true))
        .collect();
    let schema = Arc::new(Schema::new(fields));
    let arrays = columns.into_iter().map(|(_, array)| array).collect();
    let batch = RecordBatch::try_new(Arc::clone(&schema), arrays).unwrap();
    let mut bytes = Vec::new();
    let mut writer = StreamWriter::try_new(&mut bytes, &schema).unwrap();
    writer.write(&batch).unwrap();
    writer.finish().unwrap();
    bytes
}

fn times(values: &[i64]) -> ArrayRef {
    Arc::new(TimestampNanosecondArray::from(values.to_vec()).with_timezone("UTC"))
}

fn floats(values: &[Option<f64>]) -> ArrayRef {
    Arc::new(Float64Array::from(values.to_vec()))
}

fn split(data: &[u8], parts: usize) -> Vec<&[u8]> {
    data.chunks(data.len().div_ceil(parts)).collect()
}

fn series_chunks(request_id: u64, data: &[u8], parts: usize) -> Vec<ServerMessage> {
    let pieces = split(data, parts);
    let count = pieces.len();
    pieces
        .into_iter()
        .enumerate()
        .map(|(index, piece)| {
            let chunk = Series {
                index: index as u64,
                last: index + 1 == count,
                data: piece.to_vec(),
            };
            reply(request_id, Body::Series(chunk))
        })
        .collect()
}

fn panel_chunks(request_id: u64, data: &[u8]) -> Vec<ServerMessage> {
    let chunk = Panel {
        index: 0,
        last: true,
        data: data.to_vec(),
    };
    vec![reply(request_id, Body::Panel(chunk))]
}

#[tokio::test]
async fn get_run_returns_the_run_summary() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        let Some(client_message::Body::GetRun(get)) = request.body else {
            panic!("not a GetRun");
        };
        assert_eq!(get.run_id, "r1");
        let summary = RunSummary {
            run_id: "r1".to_owned(),
            strategy: "ema".to_owned(),
            ..RunSummary::default()
        };
        let body = Body::RunSummary(Box::new(summary));
        peer.send(reply(request.request_id, body)).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let run = session.get_run("r1").await.unwrap();

    assert_eq!((run.run_id.as_str(), run.strategy.as_str()), ("r1", "ema"));
}

#[tokio::test]
async fn get_metrics_joins_the_entries_of_all_chunks() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        assert!(matches!(
            request.body,
            Some(client_message::Body::GetMetrics(_))
        ));
        let id = request.request_id;
        peer.send(metrics_chunk(id, 0, false, &["a", "b"])).await;
        peer.send(metrics_chunk(id, 1, true, &["c"])).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let metrics = session.get_metrics("r1").await.unwrap();

    let names: Vec<_> = metrics.entries.iter().map(|m| m.name.as_str()).collect();
    assert_eq!(metrics.currency, "USD");
    assert_eq!(names, ["a", "b", "c"]);
}

#[tokio::test]
async fn a_server_error_keeps_its_code_and_message() {
    let address = serve(|_, mut peer| async move {
        peer.greet().await;
        let request = peer.receive().await.unwrap();
        let error = error_reply(request.request_id, ErrorCode::NotFound, "no such run");
        peer.send(error).await;
        peer.receive().await;
    })
    .await;
    let session = connected(address).await;

    let result = session.get_run("missing").await;

    assert_eq!(
        result.err(),
        Some(ClientError::Server {
            code: ErrorCode::NotFound,
            message: "no such run".to_owned(),
        })
    );
}

#[tokio::test]
async fn get_equity_decodes_a_stream_split_over_chunks() {
    let data = arrow_stream(vec![
        ("ts_event", times(&[1, 2, 3])),
        ("currency", Arc::new(StringArray::from(vec!["USD"; 3]))),
        (
            "total_equity",
            floats(&[Some(100.0), Some(101.5), Some(99.0)]),
        ),
    ]);
    let sent = data.clone();
    let address = serve(move |_, mut peer| {
        let sent = sent.clone();
        async move {
            peer.greet().await;
            let request = peer.receive().await.unwrap();
            let Some(client_message::Body::GetSeries(get)) = request.body else {
                panic!("not a GetSeries");
            };
            assert_eq!(get.kind(), SeriesKind::Equity);
            let chunks = series_chunks(request.request_id, &sent, 3);
            assert_eq!(chunks.len(), 3);
            for chunk in chunks {
                peer.send(chunk).await;
            }
            peer.receive().await;
        }
    })
    .await;
    let session = connected(address).await;

    let points = session.get_equity("r1").await.unwrap();

    let expected = [(1, 100.0), (2, 101.5), (3, 99.0)];
    let expected: Vec<_> = expected
        .into_iter()
        .map(|(ts, value)| Point { ts, value })
        .collect();
    assert_eq!(points, expected);
}

#[tokio::test]
async fn get_fills_decodes_the_stored_columns() {
    let ids: ArrayRef = Arc::new(Int64Array::from(vec![1, 2]));
    let sides: ArrayRef = Arc::new(StringArray::from(vec!["BUY", "SELL"]));
    let data = arrow_stream(vec![
        ("trade_id", ids),
        ("side", sides),
        ("price", floats(&[Some(10.5), Some(11.0)])),
        ("ts_event", times(&[5, 6])),
    ]);
    let address = serve(move |_, mut peer| {
        let data = data.clone();
        async move {
            peer.greet().await;
            let request = peer.receive().await.unwrap();
            let Some(client_message::Body::GetSeries(get)) = request.body else {
                panic!("not a GetSeries");
            };
            assert_eq!(get.kind(), SeriesKind::Fills);
            for chunk in series_chunks(request.request_id, &data, 2) {
                peer.send(chunk).await;
            }
            peer.receive().await;
        }
    })
    .await;
    let session = connected(address).await;

    let table = session.get_fills("r1").await.unwrap();

    assert_eq!(table.columns, ["trade_id", "side", "price", "ts_event"]);
    let text = |value: &str| Cell::Text(value.to_owned());
    assert_eq!(
        table.rows,
        [
            vec![Cell::Int(1), text("BUY"), Cell::Float(10.5), Cell::Time(5)],
            vec![Cell::Int(2), text("SELL"), Cell::Float(11.0), Cell::Time(6)],
        ]
    );
}

#[tokio::test]
async fn get_panel_sends_its_kind_and_benchmark_and_decodes_the_points() {
    let data = arrow_stream(vec![
        ("ts", times(&[1, 2])),
        ("value", floats(&[None, Some(0.25)])),
    ]);
    let address = serve(move |_, mut peer| {
        let data = data.clone();
        async move {
            peer.greet().await;
            let request = peer.receive().await.unwrap();
            let Some(client_message::Body::GetPanel(get)) = request.body else {
                panic!("not a GetPanel");
            };
            let benchmark = get.benchmark.clone().unwrap();
            assert_eq!(get.run_id, "r1");
            assert_eq!(get.kind(), PanelKind::BenchmarkReturns);
            assert_eq!(benchmark.kind(), BenchmarkKind::BuyAndHold);
            assert_eq!(benchmark.instrument_id.as_deref(), Some("BTC"));
            for chunk in panel_chunks(request.request_id, &data) {
                peer.send(chunk).await;
            }
            peer.receive().await;
        }
    })
    .await;
    let session = connected(address).await;
    let benchmark = BenchmarkSelection {
        kind: BenchmarkKind::BuyAndHold.into(),
        instrument_id: Some("BTC".to_owned()),
    };

    let points = session
        .get_panel("r1", PanelKind::BenchmarkReturns, benchmark)
        .await
        .unwrap();

    assert_eq!(points.len(), 2);
    assert!(points[0].value.is_nan());
    assert_eq!((points[1].ts, points[1].value), (2, 0.25));
}
