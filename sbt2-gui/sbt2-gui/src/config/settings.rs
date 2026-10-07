use std::{fs, io, path::Path};

use serde::{Deserialize, Serialize};

const FILE: &str = "settings.toml";

/// What the GUI remembers between runs, in `settings.toml` in the config folder.
#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Settings {
    pub last_server: Option<String>,
    /// A server to connect to at start, written by the user.
    #[serde(default)]
    pub server: Option<String>,
    /// The token for `server`, written by the user; the GUI never writes it itself.
    #[serde(default)]
    pub token: Option<String>,
    #[serde(default)]
    pub theme: Theme,
}

/// The colour theme of the GUI; an unknown value in the file means light.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Theme {
    Dark,
    #[default]
    #[serde(other)]
    Light,
}

impl Settings {
    /// The saved settings; the defaults when the file is missing or unreadable.
    pub fn load(config_dir: &Path) -> Self {
        fs::read_to_string(config_dir.join(FILE))
            .ok()
            .and_then(|text| toml::from_str(&text).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, config_dir: &Path) -> io::Result<()> {
        let text = toml::to_string(self).map_err(io::Error::other)?;
        fs::create_dir_all(config_dir)?;
        fs::write(config_dir.join(FILE), text)
    }
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::*;

    #[test]
    fn the_last_server_url_is_remembered() {
        let folder = TempDir::new().unwrap();
        let settings = Settings {
            last_server: Some("wss://sbt2.example.com".to_owned()),
            ..Settings::default()
        };

        settings.save(folder.path()).unwrap();

        assert_eq!(Settings::load(folder.path()), settings);
    }

    #[test]
    fn missing_or_broken_settings_load_as_the_defaults() {
        let folder = TempDir::new().unwrap();
        assert_eq!(Settings::load(folder.path()), Settings::default());

        fs::write(folder.path().join(FILE), "not = [toml").unwrap();
        assert_eq!(Settings::load(folder.path()), Settings::default());
    }

    #[test]
    fn a_missing_theme_loads_as_light() {
        let folder = TempDir::new().unwrap();
        fs::write(folder.path().join(FILE), "last_server = \"wss://a\"\n").unwrap();

        let settings = Settings::load(folder.path());

        assert_eq!(settings.theme, Theme::Light);
        assert_eq!(settings.last_server.as_deref(), Some("wss://a"));
    }

    #[test]
    fn the_dark_theme_is_remembered() {
        let folder = TempDir::new().unwrap();
        let settings = Settings {
            theme: Theme::Dark,
            ..Settings::default()
        };

        settings.save(folder.path()).unwrap();

        assert_eq!(Settings::load(folder.path()), settings);
        let text = fs::read_to_string(folder.path().join(FILE)).unwrap();
        assert!(text.contains("theme = \"dark\""));
    }

    #[test]
    fn an_unknown_theme_loads_as_light_and_keeps_the_other_settings() {
        let folder = TempDir::new().unwrap();
        let text = "theme = \"blue\"\nlast_server = \"wss://a\"\n";
        fs::write(folder.path().join(FILE), text).unwrap();

        let settings = Settings::load(folder.path());

        assert_eq!(settings.theme, Theme::Light);
        assert_eq!(settings.last_server.as_deref(), Some("wss://a"));
    }

    #[test]
    fn a_configured_server_and_token_load_from_the_file() {
        let folder = TempDir::new().unwrap();
        let text = "server = \"wss://a\"\ntoken = \"s3cret\"\n";
        fs::write(folder.path().join(FILE), text).unwrap();

        let settings = Settings::load(folder.path());

        assert_eq!(settings.server.as_deref(), Some("wss://a"));
        assert_eq!(settings.token.as_deref(), Some("s3cret"));
        assert_eq!(settings.last_server, None);
    }

    #[test]
    fn the_server_and_token_survive_a_save() {
        let folder = TempDir::new().unwrap();
        let settings = Settings {
            server: Some("wss://a".to_owned()),
            token: Some("s3cret".to_owned()),
            ..Settings::default()
        };

        settings.save(folder.path()).unwrap();

        assert_eq!(Settings::load(folder.path()), settings);
    }
}
