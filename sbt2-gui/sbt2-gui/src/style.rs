//! The named styles and spacing that all screens share.

use iced::{Background, Border, Theme, widget::container};
use iced_aw::style::{Status, card as aw_card};

/// The gap between tiles.
pub const GAP: f32 = 12.0;

/// The padding inside a tile.
pub const PADDING: f32 = 12.0;

const RADIUS: f32 = 8.0;

/// A raised tile with a rounded border.
pub fn card(theme: &Theme) -> container::Style {
    let palette = theme.extended_palette();
    container::Style {
        background: Some(palette.background.weak.color.into()),
        border: Border {
            color: palette.background.strong.color,
            width: 1.0,
            radius: RADIUS.into(),
        },
        ..container::Style::default()
    }
}

/// The look of `card` for an `iced_aw` card, with a header tinted from the palette.
pub fn aw_card(theme: &Theme, _status: Status) -> aw_card::Style {
    let palette = theme.extended_palette();
    let card = card(theme);
    aw_card::Style {
        background: Background::Color(palette.background.weak.color),
        border_radius: RADIUS,
        border_width: card.border.width,
        border_color: card.border.color,
        head_background: Background::Color(palette.background.strong.color),
        head_text_color: palette.background.strong.text,
        body_background: Background::Color(palette.background.weak.color),
        body_text_color: palette.background.weak.text,
        ..aw_card::Style::default()
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

    #[test]
    fn the_aw_card_follows_the_theme() {
        let light = aw_card(&Theme::Light, Status::Active);
        let dark = aw_card(&Theme::Dark, Status::Active);

        assert_ne!(light.background, dark.background);
        assert_ne!(light.head_text_color, dark.head_text_color);
    }
}
