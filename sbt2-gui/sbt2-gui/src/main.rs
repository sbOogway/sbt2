use sbt2_gui::{App, Environment};

fn main() -> iced::Result {
    if std::env::args().nth(1).as_deref() == Some("--version") {
        println!("{}", sbt2_client::VERSION);
        return Ok(());
    }
    iced::application(|| App::new(Environment::system()), App::update, App::view)
        .title("sbt2")
        .theme(App::theme)
        .run()
}
