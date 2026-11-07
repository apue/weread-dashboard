import unittest
from datetime import date, datetime
from dashboard import normalize_month, TZ, build_snapshot


def timestamp(day):
    return str(int(datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()))


class MetricsTests(unittest.TestCase):
    def test_missing_day_is_not_zero_and_future_is_excluded(self):
        raw = {'baseTime': int(timestamp('2026-02-01')), 'totalReadTime': 90,
               'readDays': 1, 'readTimes': {timestamp('2026-02-01'): 30,
               timestamp('2026-02-02'): 60, timestamp('2026-02-04'): 0}}
        result = normalize_month(raw, '2026-02', date(2026, 2, 3))
        self.assertEqual([d['seconds'] for d in result['days']], [30, 60, None])
        self.assertEqual(result['totalSeconds'], 90)
        self.assertEqual(result['readDays'], 1)
        self.assertFalse(result['dailyComplete'])

    def test_total_is_authoritative_and_mismatch_visible(self):
        raw = {'baseTime': int(timestamp('2026-02-01')), 'totalReadTime': 200,
               'readDays': 1, 'readTimes': {timestamp('2026-02-01'): 100}}
        result = normalize_month(raw, '2026-02', date(2026, 2, 1))
        self.assertEqual(result['totalSeconds'], 200)
        self.assertFalse(result['reconciled'])

    def test_wrong_period_rejected(self):
        with self.assertRaises(ValueError):
            normalize_month({'baseTime': int(timestamp('2026-01-01'))}, '2026-02', date(2026, 2, 3))

    def test_leap_year_and_timezone(self):
        raw = {'baseTime': int(timestamp('2024-02-01')), 'totalReadTime': 0,
               'readDays': 0, 'readTimes': {timestamp(f'2024-02-{d:02}'): 0 for d in range(1, 30)}}
        result = normalize_month(raw, '2024-02', date(2024, 3, 2))
        self.assertEqual(len(result['days']), 29)
        self.assertTrue(result['reconciled'])

    def test_response_validation(self):
        with self.assertRaises(ValueError):
            normalize_month({'baseTime': int(timestamp('2026-02-01')), 'totalReadTime': -1}, '2026-02', date(2026, 2, 1))

    def test_no_secret_or_full_book_metadata_in_snapshot(self):
        raw = {'baseTime': int(timestamp('2026-02-01')), 'totalReadTime': 60, 'readDays': 1,
               'readTimes': {timestamp('2026-02-01'): 60}, 'private': 'SECRET',
               'readLongest': [{'book': {'title': '<script>', 'author': 'A', 'intro': 'PRIVATE'}, 'readTime': 60}]}
        snapshot = build_snapshot([normalize_month(raw, '2026-02', date(2026, 2, 1))], 'now', False)
        self.assertNotIn('SECRET', str(snapshot))
        self.assertNotIn('PRIVATE', str(snapshot))
        self.assertEqual(snapshot['months'][0]['books'][0]['title'], '<script>')


if __name__ == '__main__':
    unittest.main()
