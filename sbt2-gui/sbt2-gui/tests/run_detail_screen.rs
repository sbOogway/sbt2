use iced_test::simulator;
use sbt2_client::{
    RunMetrics,
    protocol::{Metric, MetricGroup, RunSummary},
};
use sbt2_gui::run_detail::{Loaded, Message, RunDetail};

fn metric(group: MetricGroup, name: &str, value: Option<&str>) -> Metric {
    Metric {
        group: group as i32,
        name: name.to_owned(),
        value: value.map(str::to_owned),
        instrument_id: None,
    }
}

fn overview_detail() -> RunDetail {
    let mut detail = RunDetail::default();
    detail.open("run-1");
    let summary = RunSummary {
        strategy: "momentum".to_owned(),
        ..RunSummary::default()
    };
    let metrics = RunMetrics {
        currency: "USD".to_owned(),
        entries: vec![
            metric(MetricGroup::Returns, "Sharpe Ratio", Some("1.75")),
            metric(MetricGroup::Pnls, "PnL (total)", Some("1234.5")),
        ],
    };
    let loaded = [
        Loaded::Summary(Ok(Box::new(summary))),
        Loaded::Metrics(Ok(metrics)),
    ];
    for loaded in loaded {
        detail.update(Message::Loaded("run-1".to_owned(), loaded));
    }
    detail
}

#[test]
fn the_overview_shows_the_runs_metrics() {
    let detail = overview_detail();

    let mut ui = simulator(detail.view());

    for expected in ["momentum", "Sharpe Ratio", "1.75", "PnL (total)", "1234.5"] {
        assert!(ui.find(expected).is_ok(), "{expected} is not shown");
    }
}
