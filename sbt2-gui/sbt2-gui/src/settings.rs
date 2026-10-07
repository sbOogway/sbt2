use std::{
    fs, io,
    path::{Path, PathBuf},
};

use directories::BaseDirs;
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

/// `sbt2-gui` in the OS config folder, or in the working folder without a home folder.
pub fn config_dir() -> PathBuf {
    config_dir_in(BaseDirs::new().map(|dirs| dirs.config_dir().to_path_buf()))
}

fn config_dir_in(base: Option<PathBuf>) -> PathBuf {
    base.unwrap_or_else(|| PathBuf::from(".")).join(APP_FOLDER)
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
    fn the_config_folder_is_sbt2_gui_in_the_os_config_folder() {
        assert_eq!(
            config_dir_in(Some(PathBuf::from("/c"))),
            PathBuf::from("/c/sbt2-gui")
        );
    }

    #[test]
    fn without_a_home_the_config_folder_is_sbt2_gui_in_the_working_folder() {
        assert_eq!(config_dir_in(None), PathBuf::from("./sbt2-gui"));
    }
}
