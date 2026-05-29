from duration import parse_duration


def test_minutes_are_sixty_seconds():
    # 45 minutes is 45 * 60 = 2700 seconds.
    assert parse_duration("45m") == 2700


def test_hours_are_thirty_six_hundred_seconds():
    # 1 hour is 3600 seconds.
    assert parse_duration("1h") == 3600


def test_combined_hms():
    # 1h30m15s == 3600 + 1800 + 15 == 5415 seconds.
    assert parse_duration("1h30m15s") == 5415


def test_hour_and_minute():
    # 2h15m == 7200 + 900 == 8100 seconds.
    assert parse_duration("2h15m") == 8100


def test_minute_dominates_over_second():
    # 1m1s == 60 + 1 == 61 seconds (would be 7 on the buggy 6x multiplier).
    assert parse_duration("1m1s") == 61
