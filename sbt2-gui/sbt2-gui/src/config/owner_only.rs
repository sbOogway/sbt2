//! Files that only their owner can read.

use std::{fs, io, path::Path};

#[cfg(unix)]
pub(super) fn open_owner_only(path: &Path) -> io::Result<fs::File> {
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
pub(super) fn open_owner_only(path: &Path) -> io::Result<fs::File> {
    fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)
}

/// Creates the file `path` owner-only; fails with `AlreadyExists` when it exists.
#[cfg(unix)]
pub(super) fn create_owner_only(path: &Path) -> io::Result<fs::File> {
    use std::os::unix::fs::OpenOptionsExt;

    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
}

#[cfg(not(unix))]
pub(super) fn create_owner_only(path: &Path) -> io::Result<fs::File> {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
}

/// Whether group or others can read the file.
#[cfg(unix)]
pub(super) fn others_can_read(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;

    const GROUP_AND_OTHERS: u32 = 0o077;
    fs::metadata(path).is_ok_and(|meta| meta.permissions().mode() & GROUP_AND_OTHERS != 0)
}

#[cfg(not(unix))]
pub(super) fn others_can_read(_path: &Path) -> bool {
    false
}
