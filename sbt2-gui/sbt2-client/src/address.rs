use std::fmt;

use url::Url;

use crate::ClientError;

/// The `ws://` or `wss://` URL of a server.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerAddress(Url);

impl ServerAddress {
    pub fn parse(text: &str) -> Result<Self, ClientError> {
        let invalid = || ClientError::InvalidAddress(text.to_owned());
        let url = Url::parse(text.trim()).map_err(|_| invalid())?;
        match (url.scheme(), url.host_str()) {
            ("ws" | "wss", Some(_)) => Ok(Self(url)),
            _ => Err(invalid()),
        }
    }
}

impl fmt::Display for ServerAddress {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0.as_str())
    }
}

/// The API token the server admits, sent as a bearer token.
#[derive(Clone, PartialEq, Eq)]
pub struct Token(String);

impl Token {
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    pub(crate) fn expose(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for Token {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("Token(..)")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_ws_and_wss_urls_are_accepted() {
        for good in [
            "ws://localhost:8765",
            "wss://sbt2.example.com/",
            " ws://127.0.0.1:1 ",
        ] {
            assert!(ServerAddress::parse(good).is_ok(), "{good}");
        }
        for bad in [
            "http://localhost",
            "https://x.example",
            "localhost:8765",
            "",
            "ws://",
            "ftp://x",
        ] {
            assert_eq!(
                ServerAddress::parse(bad),
                Err(ClientError::InvalidAddress(bad.to_owned())),
                "{bad}"
            );
        }
    }

    #[test]
    fn a_token_does_not_show_in_debug_output() {
        assert!(!format!("{:?}", Token::new("s3cret")).contains("s3cret"));
    }
}
