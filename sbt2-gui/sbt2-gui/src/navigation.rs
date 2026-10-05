use sbt2_client::protocol::{Capability, Welcome};

/// A part of the GUI that needs a capability of the server.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Runs,
    Config,
}

impl Area {
    pub fn title(self) -> &'static str {
        match self {
            Self::Runs => "Runs",
            Self::Config => "Config",
        }
    }

    fn capability(self) -> Capability {
        match self {
            Self::Runs => Capability::Results,
            Self::Config => Capability::Config,
        }
    }
}

/// The areas the server advertises, in menu order.
pub fn areas(welcome: &Welcome) -> Vec<Area> {
    [Area::Runs, Area::Config]
        .into_iter()
        .filter(|area| welcome.capabilities.contains(&(area.capability() as i32)))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn welcome(capabilities: &[Capability]) -> Welcome {
        Welcome {
            server_version: "1".to_owned(),
            capabilities: capabilities.iter().map(|each| *each as i32).collect(),
        }
    }

    #[test]
    fn the_navigation_shows_only_the_areas_the_server_advertises() {
        assert_eq!(areas(&welcome(&[Capability::Results])), [Area::Runs]);
        assert_eq!(
            areas(&welcome(&[Capability::Config, Capability::Results])),
            [Area::Runs, Area::Config]
        );
        assert_eq!(areas(&welcome(&[])), []);
    }
}
