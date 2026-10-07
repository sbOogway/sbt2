use std::time::Duration;

/// How long a session waits between attempts to reconnect: the delay doubles
/// with each failed attempt, up to a cap.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Backoff {
    initial: Duration,
    cap: Duration,
}

impl Backoff {
    pub fn new(initial: Duration, cap: Duration) -> Self {
        Self { initial, cap }
    }

    /// The wait before the attempt after `failures` failed ones.
    pub(crate) fn delay(&self, failures: u32) -> Duration {
        let doubled = self.initial.saturating_mul(2u32.saturating_pow(failures));
        doubled.min(self.cap)
    }
}

impl Default for Backoff {
    fn default() -> Self {
        Self::new(Duration::from_millis(500), Duration::from_secs(30))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reconnect_backoff_doubles_up_to_its_cap() {
        let backoff = Backoff::new(Duration::from_secs(1), Duration::from_secs(10));

        let delays: Vec<_> = (0..6).map(|failures| backoff.delay(failures)).collect();

        let seconds: Vec<_> = delays.iter().map(Duration::as_secs).collect();
        assert_eq!(seconds, [1, 2, 4, 8, 10, 10]);
        assert_eq!(backoff.delay(u32::MAX), Duration::from_secs(10));
    }
}
