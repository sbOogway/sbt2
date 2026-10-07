//! What the GUI remembers between runs, in the config folder: its settings and the
//! server tokens.

mod settings;
mod token_store;

use std::path::PathBuf;

use directories::BaseDirs;

pub use settings::Settings;
pub use token_store::{Storage, TokenStore};

const APP_FOLDER: &str = "sbt2-gui";

/// `sbt2-gui` in the OS config folder, or in the working folder without a home folder.
pub fn config_dir() -> PathBuf {
    config_dir_in(BaseDirs::new().map(|dirs| dirs.config_dir().to_path_buf()))
}

fn config_dir_in(base: Option<PathBuf>) -> PathBuf {
    base.unwrap_or_else(|| PathBuf::from(".")).join(APP_FOLDER)
}

#[cfg(test)]
mod tests {
    use super::*;

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
