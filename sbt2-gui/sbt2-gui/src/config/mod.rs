//! What the GUI remembers between runs, in the config folder: its settings and the
//! server tokens.

mod owner_only;
mod settings;
mod token_store;

use std::{
    fs, io,
    path::{Path, PathBuf},
};

use directories::BaseDirs;

pub use settings::{Settings, Theme};
pub use token_store::{Storage, TokenStore};

const APP_FOLDER: &str = "sbt2-gui";

/// `sbt2-gui` in the OS config folder, or in the working folder without a home folder.
pub fn config_dir() -> PathBuf {
    config_dir_in(BaseDirs::new().map(|dirs| dirs.config_dir().to_path_buf()))
}

fn config_dir_in(base: Option<PathBuf>) -> PathBuf {
    base.unwrap_or_else(|| PathBuf::from(".")).join(APP_FOLDER)
}

/// Creates the config folder `dir` with its parents when it is missing. On Unix a new
/// folder is owner-only, as it can hold the token file; an existing one is left as it is.
pub fn create_folder(dir: &Path) -> io::Result<()> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;

        builder.mode(0o700);
    }
    builder.create(dir)
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

    #[test]
    fn a_missing_config_folder_is_created_with_its_parents() {
        let root = tempfile::TempDir::new().unwrap();
        let dir = root.path().join("a/b/sbt2-gui");

        create_folder(&dir).unwrap();

        assert!(dir.is_dir());
    }

    #[cfg(unix)]
    #[test]
    fn a_new_config_folder_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::TempDir::new().unwrap();
        let dir = root.path().join("sbt2-gui");

        create_folder(&dir).unwrap();

        let mode = fs::metadata(&dir).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o700);
    }

    #[cfg(unix)]
    #[test]
    fn an_existing_config_folder_keeps_its_permissions() {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::TempDir::new().unwrap();
        let dir = root.path().join("sbt2-gui");
        fs::create_dir(&dir).unwrap();
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o755)).unwrap();

        create_folder(&dir).unwrap();

        let mode = fs::metadata(&dir).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o755);
    }
}
