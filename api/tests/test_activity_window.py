"""activity_window: America/Denver local-midnight windows, DST-correct, ending at now."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.services import accounts


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def test_today_7d_30d_boundaries() -> None:
    # 2026-10-14 14:00 MDT; microseconds must be dropped from the end.
    now = datetime(2026, 10, 14, 20, 0, 0, 123456, tzinfo=UTC)

    today = accounts.activity_window("today", now)
    assert today.start == _utc(2026, 10, 14, 6)
    assert today.end == _utc(2026, 10, 14, 20)
    assert (today.start_date, today.end_date) == (date(2026, 10, 14), date(2026, 10, 14))
    assert today.timezone == "America/Denver"
    assert today.partial is True
    assert today.key == "today"

    week = accounts.activity_window("7d", now)
    assert week.start == _utc(2026, 10, 8, 6)
    assert week.start_date == date(2026, 10, 8)
    assert week.end == today.end

    month = accounts.activity_window("30d", now)
    assert month.start == _utc(2026, 9, 15, 6)
    assert month.start_date == date(2026, 9, 15)


def test_late_evening_local_time_uses_local_date_not_utc_date() -> None:
    # 23:30 MDT on Oct 14 is already Oct 15 in UTC.
    now = _utc(2026, 10, 15, 5, 30)
    window = accounts.activity_window("today", now)
    assert window.start == _utc(2026, 10, 14, 6)
    assert window.start_date == date(2026, 10, 14)
    assert window.end_date == date(2026, 10, 14)
    assert window.end == now


def test_now_exactly_at_local_midnight_never_yields_an_empty_range() -> None:
    # 2026-10-14T06:00:00Z is exactly 00:00 MDT on Oct 14.
    now = _utc(2026, 10, 14, 6)
    window = accounts.activity_window("today", now)
    assert window.start == now
    assert window.end == now + timedelta(seconds=1)
    assert window.start_date == window.end_date == date(2026, 10, 14)


def test_dst_fall_back_changes_start_offset_per_date() -> None:
    # DST ended 2026-11-01. Nov 2 midnight is MST (UTC-7); Oct 27 midnight is MDT (UTC-6).
    now = _utc(2026, 11, 2, 18)
    assert accounts.activity_window("today", now).start == _utc(2026, 11, 2, 7)
    assert accounts.activity_window("7d", now).start == _utc(2026, 10, 27, 6)


def test_dst_spring_forward_window_spans_the_change() -> None:
    # DST began 2027-03-14. Mar 9 midnight is MST (UTC-7); Mar 15 midnight is MDT (UTC-6).
    now = _utc(2027, 3, 15, 18)
    assert accounts.activity_window("today", now).start == _utc(2027, 3, 15, 6)
    week = accounts.activity_window("7d", now)
    assert week.start == _utc(2027, 3, 9, 7)
    assert week.start_date == date(2027, 3, 9)
    assert accounts.activity_window("30d", now).start == _utc(2027, 2, 14, 7)


def test_non_utc_now_is_normalised() -> None:
    from zoneinfo import ZoneInfo

    local = datetime(2026, 10, 14, 14, 0, tzinfo=ZoneInfo("America/Denver"))
    assert accounts.activity_window("today", local).end == _utc(2026, 10, 14, 20)


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        accounts.activity_window("today", datetime(2026, 10, 14, 12, 0))


def test_provider_time_format_is_z_suffixed_seconds_only() -> None:
    window = accounts.activity_window("7d", datetime(2026, 10, 14, 20, 0, 5, 999, tzinfo=UTC))
    assert accounts._provider_time(window.start) == "2026-10-08T06:00:00Z"
    assert accounts._provider_time(window.end) == "2026-10-14T20:00:05Z"
