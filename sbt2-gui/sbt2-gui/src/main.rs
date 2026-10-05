use sbt2_gui::{App, Environment};

fn main() -> iced::Result {
    iced::application(|| App::new(Environment::system()), App::update, App::view)
        .title("sbt2")
        .theme(iced::Theme::Dark)
        .run()
}
