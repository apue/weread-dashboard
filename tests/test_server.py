import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from dashboard import handler_for, Store, synchronize, fetch_month


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store, demo=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, **kwargs):
        return urllib.request.urlopen(urllib.request.Request(self.url + path, **kwargs))

    def test_demo_works_without_key(self):
        with patch('dashboard.load_key', side_effect=AssertionError('must not read credentials')):
            with self.request('/api/dashboard') as response:
                data = json.load(response)
        self.assertTrue(data['demo'])
        self.assertEqual(len(data['months']), 12)

    def test_private_paths_never_served(self):
        for path in ['/.env', '/.local/reading.sqlite3', '/dashboard.py', '/../.env']:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_cross_origin_and_rebinding_blocked(self):
        for headers in [{'Origin': 'https://evil.example'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/dashboard', headers=headers)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()

    def test_sync_requires_custom_header(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/sync', method='POST')
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        with self.request('/api/sync', method='POST', headers={'X-WeRead-Client': 'dashboard'}) as response:
            self.assertTrue(json.load(response)['demo'])

    def test_failed_sync_preserves_previous_snapshot(self):
        original = {'months': [], 'syncedAt': 'original'}
        self.store.write(original)
        with patch('dashboard.load_key', return_value='test'), patch('dashboard.fetch_month', side_effect=ValueError('network')):
            with self.assertRaises(ValueError):
                synchronize(self.store)
        self.assertEqual(self.store.read(), original)

    def test_upgrade_stops_sync(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"upgrade_info":{"message":"upgrade"}}'
        with patch('dashboard.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaisesRegex(ValueError, '升级'):
                fetch_month('2026-01', 'test')


if __name__ == '__main__':
    unittest.main()
