use sbt2_client::ClientError;

/// Data that a request is loading, has delivered or has failed to deliver.
#[derive(Debug, Clone, Default, PartialEq)]
pub enum Section<T> {
    #[default]
    Loading,
    Ready(T),
    Failed(String),
}

impl<T> From<Result<T, ClientError>> for Section<T> {
    fn from(result: Result<T, ClientError>) -> Self {
        match result {
            Ok(data) => Self::Ready(data),
            Err(error) => Self::Failed(error.to_string()),
        }
    }
}
