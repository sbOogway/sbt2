#[test]
fn the_simulator_draws_on_the_cpu() {
    assert_eq!(
        std::env::var("ICED_TEST_BACKEND").as_deref(),
        Ok("tiny-skia")
    );
}
