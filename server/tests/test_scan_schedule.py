"""Unit test jadwal scan otomatis (compute_next_run, parse_*). Jalankan di dalam image:
    docker exec rani-inv-api-1 sh -c "cd /srv && python -m unittest discover -s tests -v"
"""
import unittest
from datetime import datetime, timezone

from app.models import ScanGroup
from app.scheduler import compute_next_run, parse_schedule_days, parse_schedule_time, schedule_zone


def make_group(**over):
    fields = {
        "name": "grup-test",
        "schedule_enabled": True,
        "schedule_mode": "interval",
        "schedule_interval_min": 360,
        "schedule_time": None,
        "schedule_days": None,
    }
    fields.update(over)
    return ScanGroup(**fields)  # type: ignore[arg-type]


class ScheduleNextRunTest(unittest.TestCase):
    def test_interval_minutes(self):
        group = make_group(schedule_mode="interval", schedule_interval_min=30)
        now = datetime.now(timezone.utc)
        nxt = compute_next_run(group, now)
        self.assertIsNotNone(nxt)
        self.assertTrue(nxt >= now)

    def test_interval_clamped_to_minimum(self):
        group = make_group(schedule_mode="interval", schedule_interval_min=0)
        nxt = compute_next_run(group, datetime.now(timezone.utc))
        self.assertIsNotNone(nxt)

    def test_time_mode_daily_next_day(self):
        group = make_group(schedule_mode="time", schedule_time="02:30")
        now = datetime(2026, 11, 22, 2, 31, tzinfo=timezone.utc)  # waktu sudah lewat
        nxt = compute_next_run(group, now)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.hour, 19)  # 02:30 WIB keesokan (UTC+7)
        self.assertEqual(nxt.minute, 30)

    def test_time_mode_today(self):
        group = make_group(schedule_mode="time", schedule_time="02:30")
        now = datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)
        nxt = compute_next_run(group, now)
        self.assertEqual(nxt.hour, 19)
        self.assertEqual(nxt.minute, 30)

    def test_time_mode_days(self):
        # Senin=1 .. Minggu=7. Sekarang = Rabu (3); target Senin (1).
        group = make_group(schedule_mode="time", schedule_time="02:00",
                           schedule_days="1")
        now = datetime(2026, 11, 25, 5, 0, tzinfo=timezone.utc)  # Rabu
        nxt = compute_next_run(group, now)
        self.assertIsNotNone(nxt)
        nxt_local = nxt.astimezone(schedule_zone())
        self.assertEqual(nxt_local.isoweekday(), 1)  # Senin berikutnya
        self.assertEqual((nxt_local.hour, nxt_local.minute), (2, 0))

    def test_disabled_returns_none(self):
        group = make_group(schedule_enabled=False)
        self.assertIsNone(compute_next_run(group, datetime.now(timezone.utc)))


class ScheduleParsingTest(unittest.TestCase):
    def test_parse_time_valid(self):
        self.assertEqual(parse_schedule_time("02:30"), (2, 30))
        self.assertEqual(parse_schedule_time("23:59"), (23, 59))
        self.assertIsNone(parse_schedule_time("24:00"))
        self.assertIsNone(parse_schedule_time("abc"))
        self.assertIsNone(parse_schedule_time(""))

    def test_parse_days(self):
        self.assertEqual(parse_schedule_days("1,3,5"), {1, 3, 5})
        self.assertEqual(parse_schedule_days(""), set())
        self.assertEqual(parse_schedule_days(None), set())
        self.assertEqual(parse_schedule_days("8"), set())


if __name__ == "__main__":
    unittest.main()
