use std::{
    collections::BTreeMap,
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    sync::Arc,
};

use keyring_core::{CredentialStore, Entry};

const SERVICE: &str = "sbt2-gui";
const FALLBACK_FILE: &str = "tokens.toml";

/// Where a token was kept.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Storage {
    Keyring,
    /// A file only its owner can read: the OS keyring is not available.
    File,
}

/// Keeps the token of each server in the OS keyring, or in a file only its owner
/// can read (`0600` on Unix) in the config folder when there is no keyring.
pub struct TokenStore {
    keyring: Option<Arc<CredentialStore>>,
    fallback: PathBuf,
}

impl TokenStore {
    pub fn new(keyring: Option<Arc<CredentialStore>>, config_dir: &Path) -> Self {
        Self {
            keyring,
            fallback: config_dir.join(FALLBACK_FILE),
        }
    }

    /// A store on the keyring of the OS, or on the file alone when it is not reachable.
    pub fn system(config_dir: &Path) -> Self {
        Self::new(native_keyring(), config_dir)
    }

    pub fn save(&self, server: &str, token: &str) -> io::Result<Storage> {
        if self.save_in_keyring(server, token) {
            return Ok(Storage::Keyring);
        }
        self.save_in_file(server, token)?;
        Ok(Storage::File)
    }

    pub fn load(&self, server: &str) -> Option<String> {
        self.entry(server)
            .and_then(|entry| entry.get_password().ok())
            .or_else(|| self.read_file().remove(server))
    }

    fn entry(&self, server: &str) -> Option<Entry> {
        self.keyring.as_ref()?.build(SERVICE, server, None).ok()
    }

    fn save_in_keyring(&self, server: &str, token: &str) -> bool {
        self.entry(server)
            .is_some_and(|entry| entry.set_password(token).is_ok())
    }

    fn save_in_file(&self, server: &str, token: &str) -> io::Result<()> {
        let mut tokens = self.read_file();
        tokens.insert(server.to_owned(), token.to_owned());
        let text = toml::to_string(&tokens).map_err(io::Error::other)?;
        if let Some(folder) = self.fallback.parent() {
            fs::create_dir_all(folder)?;
        }
        let mut file = open_owner_only(&self.fallback)?;
        file.write_all(text.as_bytes())
    }

    fn read_file(&self) -> BTreeMap<String, String> {
        fs::read_to_string(&self.fallback)
            .ok()
            .and_then(|text| toml::from_str(&text).ok())
            .unwrap_or_default()
    }
}

#[cfg(target_os = "linux")]
fn native_keyring() -> Option<Arc<CredentialStore>> {
    let store = zbus_secret_service_keyring_store::Store::new().ok()?;
    Some(store)
}

#[cfg(target_os = "macos")]
fn native_keyring() -> Option<Arc<CredentialStore>> {
    let store = apple_native_keyring_store::keychain::Store::new().ok()?;
    Some(store)
}

#[cfg(target_os = "windows")]
fn native_keyring() -> Option<Arc<CredentialStore>> {
    let store = windows_native_keyring_store::Store::new().ok()?;
    Some(store)
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn native_keyring() -> Option<Arc<CredentialStore>> {
    None
}

#[cfg(unix)]
fn open_owner_only(path: &Path) -> io::Result<fs::File> {
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

    const OWNER_ONLY: u32 = 0o600;
    let file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(OWNER_ONLY)
        .open(path)?;
    file.set_permissions(fs::Permissions::from_mode(OWNER_ONLY))?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_owner_only(path: &Path) -> io::Result<fs::File> {
    fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)
}

#[cfg(test)]
mod tests {
    use keyring_core::{Error, mock::Cred, mock::Store};
    use tempfile::TempDir;

    use super::*;

    const SERVER: &str = "wss://sbt2.example.com";

    fn mock_keyring() -> Arc<CredentialStore> {
        Store::new().unwrap()
    }

    #[test]
    fn the_token_is_saved_to_and_read_from_the_keyring() {
        let folder = TempDir::new().unwrap();
        let keyring = mock_keyring();

        let saved = TokenStore::new(Some(keyring.clone()), folder.path())
            .save(SERVER, "s3cret")
            .unwrap();

        assert_eq!(saved, Storage::Keyring);
        let reopened = TokenStore::new(Some(keyring), folder.path());
        assert_eq!(reopened.load(SERVER).as_deref(), Some("s3cret"));
        assert!(!folder.path().join(FALLBACK_FILE).exists());
    }

    #[test]
    fn without_a_keyring_the_token_goes_to_a_file_only_its_owner_reads() {
        let folder = TempDir::new().unwrap();
        let store = TokenStore::new(None, folder.path());

        let saved = store.save(SERVER, "s3cret").unwrap();

        assert_eq!(saved, Storage::File);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            let mode = fs::metadata(folder.path().join(FALLBACK_FILE))
                .unwrap()
                .permissions()
                .mode();
            assert_eq!(mode & 0o777, 0o600);
        }
        assert_eq!(store.load(SERVER).as_deref(), Some("s3cret"));
    }

    #[test]
    fn a_failing_keyring_falls_back_to_the_file() {
        let folder = TempDir::new().unwrap();
        let keyring = mock_keyring();
        let entry = keyring.build(SERVICE, SERVER, None).unwrap();
        entry
            .as_any()
            .downcast_ref::<Cred>()
            .unwrap()
            .set_error(Error::NoStorageAccess("locked".into()));
        let store = TokenStore::new(Some(keyring), folder.path());

        assert_eq!(store.save(SERVER, "s3cret").unwrap(), Storage::File);
    }

    #[test]
    fn a_token_is_never_returned_for_another_server() {
        let folder = TempDir::new().unwrap();
        let store = TokenStore::new(None, folder.path());
        store.save(SERVER, "s3cret").unwrap();

        assert_eq!(store.load("wss://other.example.com"), None);
    }
}
