use std::sync::atomic::{AtomicU64, Ordering};

/// Allocates request ids: never 0, never repeated.
#[derive(Debug, Default)]
pub(crate) struct RequestIds(AtomicU64);

impl RequestIds {
    pub(crate) fn next(&self) -> u64 {
        self.0.fetch_add(1, Ordering::Relaxed) + 1
    }
}

#[cfg(test)]
mod tests {
    use std::{collections::HashSet, sync::Arc, thread};

    use super::*;

    #[test]
    fn request_ids_start_at_one_and_never_repeat() {
        let ids = Arc::new(RequestIds::default());
        assert_eq!(ids.next(), 1);
        let workers: Vec<_> = (0..8)
            .map(|_| {
                let ids = Arc::clone(&ids);
                thread::spawn(move || (0..1000).map(|_| ids.next()).collect::<Vec<_>>())
            })
            .collect();
        let mut seen = HashSet::from([1]);
        for worker in workers {
            for id in worker.join().unwrap() {
                assert_ne!(id, 0);
                assert!(seen.insert(id), "{id} repeated");
            }
        }
        assert_eq!(seen.len(), 8001);
    }
}
