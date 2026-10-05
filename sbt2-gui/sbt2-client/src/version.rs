//! Maps the release variable and `git describe` to the version string. Shared with `build.rs`.

const LOCAL: &str = "0.0.0+local";

/// The release variable wins, then the `git describe --long` output, then a local marker.
pub fn stamp(variable: Option<&str>, describe: Option<&str>) -> String {
    variable
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .or_else(|| describe.and_then(from_describe))
        .unwrap_or_else(|| LOCAL.to_owned())
}

fn from_describe(describe: &str) -> Option<String> {
    let (rest, hash) = describe.trim().rsplit_once("-g")?;
    let (tag, distance) = rest.rsplit_once('-')?;
    let release = tag.strip_prefix('v')?;
    match distance.parse::<u32>().ok()? {
        0 => Some(release.to_owned()),
        distance => Some(format!("{release}.post{distance}.dev0+{hash}")),
    }
}

#[cfg(test)]
mod tests {
    use super::stamp;

    #[test]
    fn the_release_variable_wins_over_git() {
        let version = stamp(Some("0.8.0"), Some("v0.7.6-14-gd7376f6"));
        assert_eq!(version, "0.8.0");
    }

    #[test]
    fn a_tagged_commit_is_its_tag_without_the_v() {
        assert_eq!(stamp(None, Some("v0.7.6-0-gd7376f6")), "0.7.6");
    }

    #[test]
    fn commits_after_a_tag_follow_the_python_packages_format() {
        let version = stamp(None, Some("v0.7.6-14-gd7376f6"));
        assert_eq!(version, "0.7.6.post14.dev0+d7376f6");
    }

    #[test]
    fn without_a_variable_or_git_the_version_is_local() {
        assert_eq!(stamp(None, None), "0.0.0+local");
    }
}
