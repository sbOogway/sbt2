use iced_test::simulator;
use sbt2_client::{
    Point, RunMetrics,
    protocol::{Metric, MetricGroup, RunSummary},
};
use sbt2_gui::screens::run_detail::{Loaded, Message, RunDetail, Tab, charts::Chart};

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
fn the_detail_tabs_and_back_emit_their_messages() {
    let detail = overview_detail();

    let mut ui = simulator(detail.view());
    ui.click("Charts").unwrap();
    ui.click("Fills").unwrap();
    ui.click("Back").unwrap();
    let messages: Vec<Message> = ui.into_messages().collect();

    assert!(matches!(messages[0], Message::Show(Tab::Charts)));
    assert!(matches!(messages[1], Message::Show(Tab::Fills)));
    assert!(matches!(messages[2], Message::Back));
}

#[test]
fn the_overview_shows_the_runs_metrics() {
    let detail = overview_detail();

    let mut ui = simulator(detail.view());

    for expected in ["momentum", "Sharpe Ratio", "1.75", "PnL (total)", "1234.5"] {
        assert!(ui.find(expected).is_ok(), "{expected} is not shown");
    }
}

#[test]
fn the_charts_tab_draws_each_chart_with_its_title() {
    let mut detail = overview_detail();
    detail.update(Message::Show(Tab::Charts));
    let day = 86_400 * 1_000_000_000;
    let points: Vec<Point> = (0..40)
        .map(|index| Point {
            ts: 1_704_067_200 * 1_000_000_000 + index * day,
            value: if index % 9 == 0 {
                f64::NAN
            } else {
                index as f64 / 100.0
            },
        })
        .collect();
    for chart in [
        Chart::Equity,
        Chart::Drawdown,
        Chart::Returns,
        Chart::Yearly,
    ] {
        let loaded = Loaded::Chart(chart, Ok(points.clone()));
        detail.update(Message::Loaded("run-1".to_owned(), loaded));
    }
    detail.update(Message::Loaded(
        "run-1".to_owned(),
        Loaded::Benchmark(Ok(points.clone())),
    ));
    detail.update(Message::Loaded(
        "run-1".to_owned(),
        Loaded::Chart(Chart::Monthly, Ok(points)),
    ));

    let mut ui = simulator(detail.view());

    assert!(ui.snapshot(&iced::Theme::Dark).is_ok());
    for title in [
        "Equity",
        "Drawdown",
        "Daily returns",
        "Monthly returns",
        "Yearly returns",
    ] {
        assert!(ui.find(title).is_ok(), "{title} is not shown");
    }
}

#[test]
fn each_metric_group_shows_its_title_in_a_card() {
    let detail = overview_detail();

    let mut ui = simulator(detail.view());

    for title in ["PnLs", "Returns"] {
        assert!(ui.find(title).is_ok(), "{title} is not shown");
    }
}

#[test]
fn a_tripped_drawdown_shows_its_day_in_a_badge() {
    let mut detail = RunDetail::default();
    detail.open("run-1");
    let summary = RunSummary {
        drawdown_tripped_at: Some(prost_types::Timestamp {
            seconds: 1_704_067_200,
            nanos: 0,
        }),
        ..RunSummary::default()
    };
    let loaded = Loaded::Summary(Ok(Box::new(summary)));
    detail.update(Message::Loaded("run-1".to_owned(), loaded));

    let mut ui = simulator(detail.view());

    assert!(ui.find("2024-01-01").is_ok());
}

#[test]
fn a_loading_overview_shows_no_loading_text() {
    let mut detail = RunDetail::default();
    detail.open("run-1");

    let mut ui = simulator(detail.view());

    for text in ["Loading the run...", "Loading the metrics..."] {
        assert!(ui.find(text).is_err(), "{text} is shown");
    }
}
