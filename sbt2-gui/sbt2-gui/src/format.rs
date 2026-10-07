//! Dates and times in UTC.

/// The year, month and day of a Unix time in seconds.
pub fn civil(seconds: i64) -> (i64, i64, i64) {
    let days = seconds.div_euclid(86_400) + 719_468;
    let era = days.div_euclid(146_097);
    let day_of_era = days.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted_month = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
    let month = if shifted_month < 10 {
        shifted_month + 3
    } else {
        shifted_month - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

/// `YYYY-MM-DD` of a Unix time in seconds.
pub fn utc_day(seconds: i64) -> String {
    let (year, month, day) = civil(seconds);
    format!("{year:04}-{month:02}-{day:02}")
}

/// `YYYY-MM-DD HH:MM:SS` of a Unix time in nanoseconds.
pub fn utc_datetime(nanos: i64) -> String {
    let seconds = nanos.div_euclid(1_000_000_000);
    let second_of_day = seconds.rem_euclid(86_400);
    let (hour, minute, second) = (
        second_of_day / 3_600,
        second_of_day % 3_600 / 60,
        second_of_day % 60,
    );
    format!("{} {hour:02}:{minute:02}:{second:02}", utc_day(seconds))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dates_show_as_utc_days() {
        assert_eq!(utc_day(0), "1970-01-01");
        assert_eq!(utc_day(1_704_067_200), "2024-01-01");
        assert_eq!(utc_day(1_709_164_800), "2024-02-29");
        assert_eq!(civil(-1), (1969, 12, 31));
    }

    #[test]
    fn times_show_as_utc_days_with_seconds() {
        assert_eq!(
            utc_datetime(1_704_067_261_000_000_000),
            "2024-01-01 00:01:01"
        );
        assert_eq!(utc_datetime(-1), "1969-12-31 23:59:59");
    }
}
