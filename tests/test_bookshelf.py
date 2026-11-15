import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from email.message import Message
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from bookshelf import normalize_shelf, validate_shelf, safe_link, ShelfStore, fetch_cover
from dashboard import Store, handler_for


class ShelfTests(unittest.TestCase):
    def test_normalizes_books_albums_and_mp_including_unknown_progress(self):
        raw = {'books': [{'bookId': 'b1', 'title': 'T', 'finishReading': 1}],
               'albums': [{'albumInfo': {'albumId': 'a1', 'name': 'A', 'finish': 1}}], 'mp': {'id': 1}}
        items = normalize_shelf(raw)
        self.assertEqual([i['id'] for i in items], ['book:b1', 'album:a1', 'articles'])
        self.assertTrue(items[0]['finished'])
        self.assertIsNone(items[0]['progress'])

    def test_rejects_partial_snapshot_and_upgrade(self):
        for raw in ({'books': []}, {'books': [], 'albums': [], 'mp': [], 'upgrade_info': {}}):
            with self.assertRaises(ValueError):
                validate_shelf(raw)

    def test_rejects_invalid_book_and_album_timestamps_and_finish_flag(self):
        cases=[{'books':[{'bookId':'x','readUpdateTime':float('nan')}],'albums':[],'mp':None},
               {'books':[{'bookId':'x','finishReading':2}],'albums':[],'mp':None},
               {'books':[],'albums':[{'albumInfo':{'albumId':'a'},'albumInfoExtra':{'lectureReadUpdateTime':-1}}],'mp':None}]
        for raw in cases:
            with self.assertRaises(ValueError): validate_shelf(raw)

    def test_links_reject_active_content(self):
        self.assertIsNone(safe_link('javascript:alert(1)'))
        self.assertEqual(safe_link('https://weread.qq.com/web/reader/abc'), 'https://weread.qq.com/web/reader/abc')

    def test_cache_isolated_by_key_and_empty_snapshot_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            store = ShelfStore(Path(d) / 'db.sqlite3')
            store.save_shelf('wrk-one', [{'id':'book:1'}])
            store.save_shelf('wrk-two', [])
            self.assertEqual(store.shelf('wrk-one')['items'], [{'id':'book:1'}])
            self.assertEqual(store.shelf('wrk-two')['items'], [])

    def test_cover_host_type_and_size_are_restricted(self):
        with self.assertRaises(ValueError): fetch_cover('https://evil.example/a.jpg')
        class Response:
            headers=Message()
            def __init__(self): self.headers['Content-Type']='image/jpeg'
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self,n): return b'jpeg'
        with patch('bookshelf.urllib.request.build_opener') as openr:
            openr.return_value.open.return_value=Response()
            mime,data=fetch_cover('https://res.weread.qq.com/cover.jpg')
        self.assertEqual((mime,data),('image/jpeg',b'jpeg'))

    def test_cover_rejects_svg(self):
        class Response:
            headers=Message()
            def __init__(self): self.headers['Content-Type']='image/svg+xml'
            def __enter__(self): return self
            def __exit__(self,*a): pass
        with patch('bookshelf.urllib.request.build_opener') as openr:
            openr.return_value.open.return_value=Response()
            with self.assertRaises(ValueError): fetch_cover('https://res.weread.qq.com/cover.svg')
        with self.assertRaises(ValueError): fetch_cover('https://res.weread.qq.com:444/cover.jpg')

    def test_same_url_different_ids_reuses_download(self):
        with tempfile.TemporaryDirectory() as d:
            store=ShelfStore(Path(d)/'db.sqlite3')
            store.save_shelf('key',[{'id':'book:1'},{'id':'book:2'}],{'book:1':'https://res.weread.qq.com/same.jpg','book:2':'https://res.weread.qq.com/same.jpg'})
            with patch('bookshelf.fetch_cover',return_value=('image/jpeg',b'jpeg')) as fetch:
                self.assertEqual(store.cover('key','book:1'),('image/jpeg',b'jpeg'))
                self.assertEqual(store.cover('key','book:2'),('image/jpeg',b'jpeg'))
            fetch.assert_called_once()

    def test_demo_nav_and_local_svg_cover(self):
        with tempfile.TemporaryDirectory() as d:
            server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Store(Path(d)),demo=True))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                req=urllib.request.Request(base+'/',headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
                with urllib.request.urlopen(req) as response: self.assertEqual(response.status,200)
                req=urllib.request.Request(base+'/api/shelf',headers={'Sec-Fetch-Site':'cross-site'})
                with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
                self.assertEqual(err.exception.code,403); err.exception.close()
                with urllib.request.urlopen(base+'/api/cover?id=book%3Ademo3') as response:
                    self.assertEqual(response.headers.get_content_type(),'image/svg+xml')
                    self.assertIn(b'<svg',response.read())
                with urllib.request.urlopen(base+'/api/book?id=book%3Ademo3') as response:
                    self.assertEqual(json.load(response)['progress']['progress'],100)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
