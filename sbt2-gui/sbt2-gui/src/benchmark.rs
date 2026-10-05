use std::fmt;

use sbt2_client::protocol::{BenchmarkKind, BenchmarkSelection};

/// The benchmarks the server can compute; one for each `BenchmarkKind` the GUI offers.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum Kind {
    #[default]
    StrategyDefault,
    NoBenchmark,
    BuyAndHold,
    EqualWeight,
}

impl Kind {
    pub const ALL: [Self; 4] = [
        Self::StrategyDefault,
        Self::NoBenchmark,
        Self::BuyAndHold,
        Self::EqualWeight,
    ];

    fn protocol(self) -> BenchmarkKind {
        match self {
            Self::StrategyDefault => BenchmarkKind::Default,
            Self::NoBenchmark => BenchmarkKind::None,
            Self::BuyAndHold => BenchmarkKind::BuyAndHold,
            Self::EqualWeight => BenchmarkKind::EqualWeight,
        }
    }
}

impl fmt::Display for Kind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::StrategyDefault => "Strategy default",
            Self::NoBenchmark => "None",
            Self::BuyAndHold => "Buy and hold",
            Self::EqualWeight => "Equal weight",
        })
    }
}

/// The benchmark picked for the charts of a run.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Benchmark {
    kind: Kind,
    instrument: Option<String>,
}

impl Benchmark {
    pub fn kind(&self) -> Kind {
        self.kind
    }

    pub fn instrument(&self) -> Option<&String> {
        self.instrument.as_ref()
    }

    /// Picks a kind; buy and hold starts with the first of the run's instruments.
    pub fn choose(&mut self, kind: Kind, instruments: &[String]) {
        self.kind = kind;
        self.instrument = match kind {
            Kind::BuyAndHold => instruments.first().cloned(),
            _ => None,
        };
    }

    pub fn choose_instrument(&mut self, instrument: String) {
        self.instrument = Some(instrument);
    }

    pub fn selection(&self) -> BenchmarkSelection {
        BenchmarkSelection {
            kind: self.kind.protocol().into(),
            instrument_id: self.instrument.clone(),
        }
    }
}
