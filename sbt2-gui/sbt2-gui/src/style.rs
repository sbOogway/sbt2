//! The named styles and spacing that all screens share.

use iced::{Border, Theme, widget::container};

/// The gap between tiles.
pub const GAP: f32 = 12.0;

/// The padding inside a tile.
pub const PADDING: f32 = 12.0;

/// A raised tile with a rounded border.
pub fn card(theme: &Theme) -> container::Style {
    let palette = theme.extended_palette();
    container::Style {
        background: Some(palette.background.weak.color.into()),
        border: Border {
            color: palette.background.strong.color,
            width: 1.0,
            radius: 8.0.into(),
        },
        ..container::Style::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_card_follows_the_theme() {
        let light = card(&Theme::Light);
        let dark = card(&Theme::Dark);

        assert_ne!(light.background, dark.background);
    }
}
