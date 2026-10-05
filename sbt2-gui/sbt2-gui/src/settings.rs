use std::{
    env, fs, io,
    path::{Path, PathBuf},
};

use serde::{Deserialize, Serialize};

const FILE: &str = "settings.toml";
const APP_FOLDER: &str = "sbt2-gui";

/// What the GUI remembers between runs, in `settings.toml` in the config folder.
#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Settings {
    pub last_server: Option<String>,
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

/// `$XDG_CONFIG_HOME/sbt2-gui`, or `~/.config/sbt2-gui`.
pub fn config_dir() -> PathBuf {
    config_dir_in(env::var_os("XDG_CONFIG_HOME"), env::var_os("HOME"))
}

fn config_dir_in(xdg: Option<std::ffi::OsString>, home: Option<std::ffi::OsString>) -> PathBuf {
    let base = match (xdg.filter(|dir| !dir.is_empty()), home) {
        (Some(xdg), _) => PathBuf::from(xdg),
        (None, Some(home)) => PathBuf::from(home).join(".config"),
        (None, None) => PathBuf::from("."),
    };
    base.join(APP_FOLDER)
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
    fn the_config_folder_follows_xdg_then_home() {
        let path = |xdg: Option<&str>, home: Option<&str>| {
            config_dir_in(xdg.map(Into::into), home.map(Into::into))
        };

        assert_eq!(path(Some("/x"), Some("/h")), PathBuf::from("/x/sbt2-gui"));
        assert_eq!(path(None, Some("/h")), PathBuf::from("/h/.config/sbt2-gui"));
        assert_eq!(
            path(Some(""), Some("/h")),
            PathBuf::from("/h/.config/sbt2-gui")
        );
    }
}
