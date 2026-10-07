use std::{
    fs,
    io::{self, Write},
    path::Path,
};

use serde::{Deserialize, Serialize};

use super::owner_only::{create_owner_only, open_owner_only, others_can_read};

const FILE: &str = "settings.toml";
const TEMPLATE: &str = r#"# sbt2-gui settings. The GUI reads this file at start.

# A server to connect to at start, and its token.
# server = "wss://sbt2.example.com"
# token = "..."

# "light" or "dark"
theme = "light"
"#;

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

    /// Whether the settings file holds a token that other users can read.
    pub fn exposes_token(config_dir: &Path) -> bool {
        let path = config_dir.join(FILE);
        Self::load(config_dir).token.is_some() && others_can_read(&path)
    }

    /// Writes the commented template to a missing settings file, owner-only as the user
    /// can add a token to it. An existing file is left as it is.
    pub fn create_default(config_dir: &Path) -> io::Result<()> {
        match create_owner_only(&config_dir.join(FILE)) {
            Ok(mut file) => file.write_all(TEMPLATE.as_bytes()),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => Ok(()),
            Err(error) => Err(error),
        }
    }

    pub fn save(&self, config_dir: &Path) -> io::Result<()> {
        let text = toml::to_string(self).map_err(io::Error::other)?;
        fs::create_dir_all(config_dir)?;
        let path = config_dir.join(FILE);
        if self.token.is_some() {
            return open_owner_only(&path)?.write_all(text.as_bytes());
        }
        fs::write(path, text)
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

    #[test]
    fn a_missing_settings_file_is_created_from_the_template() {
        let folder = TempDir::new().unwrap();

        Settings::create_default(folder.path()).unwrap();

        let text = fs::read_to_string(folder.path().join(FILE)).unwrap();
        assert!(text.contains("# server = "));
        assert!(text.contains("# token = "));
        assert_eq!(Settings::load(folder.path()), Settings::default());
    }

    #[test]
    fn an_existing_settings_file_is_left_as_it_is() {
        let folder = TempDir::new().unwrap();
        fs::write(folder.path().join(FILE), "theme = \"dark\"\n").unwrap();

        Settings::create_default(folder.path()).unwrap();

        let text = fs::read_to_string(folder.path().join(FILE)).unwrap();
        assert_eq!(text, "theme = \"dark\"\n");
    }

    #[cfg(unix)]
    #[test]
    fn a_new_settings_file_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let folder = TempDir::new().unwrap();

        Settings::create_default(folder.path()).unwrap();

        let mode = fs::metadata(folder.path().join(FILE))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
    }

    #[cfg(unix)]
    fn with_mode(folder: &TempDir, text: &str, mode: u32) {
        use std::os::unix::fs::PermissionsExt;

        let file = folder.path().join(FILE);
        fs::write(&file, text).unwrap();
        fs::set_permissions(file, fs::Permissions::from_mode(mode)).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn settings_with_a_token_are_saved_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let folder = TempDir::new().unwrap();
        with_mode(&folder, "", 0o644);
        let settings = Settings {
            token: Some("s3cret".to_owned()),
            ..Settings::default()
        };

        settings.save(folder.path()).unwrap();

        let mode = fs::metadata(folder.path().join(FILE))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
    }

    #[cfg(unix)]
    #[test]
    fn a_token_file_others_can_read_is_detected() {
        let folder = TempDir::new().unwrap();

        with_mode(&folder, "token = \"s3cret\"\n", 0o644);
        assert!(Settings::exposes_token(folder.path()));

        with_mode(&folder, "token = \"s3cret\"\n", 0o600);
        assert!(!Settings::exposes_token(folder.path()));

        with_mode(&folder, "theme = \"dark\"\n", 0o644);
        assert!(!Settings::exposes_token(folder.path()));
    }
}
