"""HTTP boundary checks for bookshelf cache, isolation, and failure behavior."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import bookshelf
from dashboard import Store, handler_for


class ShelfHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store, demo=False))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.key = 'test-key-A'
        self.key_patch = patch('dashboard.load_key', return_value=self.key)
        self.key_patch.start()

    def tearDown(self):
        self.key_patch.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, method='GET', headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try: return error.code, json.load(error)
            finally: error.close()

    def post_headers(self): return {'X-WeRead-Client': 'dashboard'}

    def test_cached_get_never_calls_upstream_and_unknown_id_cannot_proxy(self):
        shelf = bookshelf.ShelfStore(self.store.path)
        shelf.save_shelf(self.key, [{'id':'book:1','kind':'book','title':'cached'}])
        with patch('bookshelf.request_api', side_effect=AssertionError('GET must be cache-only')):
            status, data = self.request('/api/shelf')
            self.assertEqual(status, 200); self.assertEqual(data['items'][0]['title'], 'cached')
            status, data = self.request('/api/book?id=book%3A999')
            self.assertIn(status, (200, 404))  # Either empty cache or not-found; never a gateway proxy.
            if status == 200: self.assertEqual(data['info'], None)

    def test_unknown_book_sync_is_rejected_without_upstream_call(self):
        with patch('bookshelf.request_api', side_effect=AssertionError('unknown id must not reach upstream')):
            status, data = self.request('/api/book/sync?id=book%3A999&part=all', 'POST', self.post_headers())
        self.assertEqual(status, 404); self.assertIn('error', data)

    def test_same_book_progress_and_all_requests_serialize_and_reuse_progress(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key, [{'id':'book:1','kind':'book','bookId':'1','title':'one'}])
        entered = threading.Event(); release = threading.Event(); calls=[]
        def upstream(_key, endpoint, **_params):
            calls.append(endpoint)
            if endpoint == '/book/getprogress':
                entered.set()
                if not release.wait(3): raise TimeoutError('test did not release progress request')
                return {'book':{'progress':1}}
            return {'title':'one','intro':'info'}
        responses=[]
        def request(part): responses.append(self.request(f'/api/book/sync?id=book%3A1&part={part}', 'POST', self.post_headers()))
        with patch('bookshelf.request_api', side_effect=upstream):
            first=threading.Thread(target=request,args=('progress',)); first.start()
            self.assertTrue(entered.wait(2),'progress request should start')
            second=threading.Thread(target=request,args=('all',)); second.start()
            release.set(); first.join(4); second.join(4)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(sorted(status for status,_ in responses), [200,200])
        self.assertEqual(calls.count('/book/getprogress'),1,'all sync reuses the concurrent fresh progress')
        self.assertEqual(calls.count('/book/info'),1)

    def test_navigation_root_allows_document_load_but_api_rejects_cross_site(self):
        nav={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        req=urllib.request.Request(self.base+'/',headers=nav)
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status,200); self.assertIn('<!doctype html',response.read().decode().lower())
        self.assertEqual(self.request('/api/shelf', headers={'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_notes_pages_are_committed_only_after_complete_pagination(self):
        shelves=bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key,[{'id':'book:1','kind':'book','bookId':'1','title':'one'}])
        shelves.save_book_part(self.key,'book:1','notes',{'noteCount':9,'reviewCount':8,'bookmarkCount':7,'total':24})
        calls=[]
        def pages(_key, endpoint, **params):
            calls.append((endpoint,params))
            if 'lastSort' not in params:
                return {'books':[{'bookId':'1','noteCount':1,'reviewCount':2,'bookmarkCount':3,'sort':10}],'hasMore':True}
            return {'books':[{'bookId':'1','noteCount':4,'reviewCount':5,'bookmarkCount':6,'sort':5}],'hasMore':False}
        with patch('bookshelf.request_api', side_effect=pages):
            status, data=self.request('/api/notes/sync','POST',self.post_headers())
        self.assertEqual(status,200,data)
        self.assertEqual([params.get('lastSort') for _,params in calls],[None,10])
        self.assertEqual(data['bookCount'],1)
        self.assertEqual(shelves.book(self.key,'book:1')['notes'],{'noteCount':4,'reviewCount':5,'bookmarkCount':6,'total':15})

    def test_missing_notes_has_more_or_interrupted_page_preserves_old_overview(self):
        shelves=bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key,[{'id':'book:1','kind':'book','bookId':'1','title':'one'}])
        original={'noteCount':9,'reviewCount':8,'bookmarkCount':7,'total':24}
        shelves.save_book_part(self.key,'book:1','notes',original)
        bad_pages=[
            lambda _key,_endpoint,**_params:{'books':[{'bookId':'1','noteCount':1,'reviewCount':1,'bookmarkCount':1}]},
            lambda _key,_endpoint,**params: ({'books':[{'bookId':'1','noteCount':1,'reviewCount':1,'bookmarkCount':1,'sort':10}],'hasMore':True} if 'lastSort' not in params else (_ for _ in ()).throw(ValueError('interrupted'))),
            lambda _key,_endpoint,**params: ({'books':[{'bookId':'1','noteCount':1,'reviewCount':1,'bookmarkCount':1,'sort':10}],'hasMore':True} if 'lastSort' not in params else {'books':[{'bookId':'1','noteCount':1,'reviewCount':1,'bookmarkCount':1,'sort':11}],'hasMore':True}),
        ]
        for index,upstream in enumerate(bad_pages):
            with patch('bookshelf.request_api', side_effect=upstream):
                status,_=self.request('/api/notes/sync','POST',self.post_headers())
            with self.subTest(invalid_page=index):
                self.assertGreaterEqual(status,400)
                self.assertEqual(shelves.book(self.key,'book:1')['notes'],original)

    def test_partial_detail_failure_keeps_previous_part_and_returns_new_part(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key, [{'id':'book:1','kind':'book','bookId':'1','title':'one'}])
        shelves.save_book_part(self.key, 'book:1', 'info', {'intro':'cached info'})
        shelves.save_book_part(self.key, 'book:1', 'progress', {'progress':1})
        with closing(sqlite3.connect(self.store.path)) as db:
            with db:
                db.execute("UPDATE books SET info_at='2000-01-01T00:00:00+0000', progress_at='2000-01-01T00:00:00+0000' WHERE id='book:1'")
        def upstream(_key, endpoint, **_params):
            if endpoint == '/book/info': raise ValueError('info unavailable')
            return {'book': {'progress':100, 'recordReadingTime':60}}
        with patch('bookshelf.request_api', side_effect=upstream):
            status, data = self.request('/api/book/sync?id=book%3A1&part=all', 'POST', self.post_headers())
        self.assertIn(status, (200, 502)); self.assertTrue(data['errors'], data)
        self.assertEqual(data['info']['intro'], 'cached info')
        self.assertEqual(data['progress']['progress'], 100)

    def test_upgrade_in_info_stops_before_progress_request(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key, [{'id':'book:1','kind':'book','bookId':'1','title':'one'}])
        calls=[]
        def upstream(_key, endpoint, **_params):
            calls.append(endpoint)
            raise bookshelf.UpgradeRequired('upgrade')
        with patch('bookshelf.request_api', side_effect=upstream):
            status, data = self.request('/api/book/sync?id=book%3A1&part=all', 'POST', self.post_headers())
        self.assertGreaterEqual(status, 400)
        self.assertEqual(calls, ['/book/info'])

    def test_same_cover_url_keeps_cached_image(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        sources={'book:1':'https://cdn.weread.qq.com/covers/one.jpg'}
        shelves.save_shelf(self.key, [], sources)
        with patch('bookshelf.fetch_cover', return_value=('image/jpeg',b'cover')) as fetch:
            self.assertEqual(shelves.cover(self.key,'book:1'), ('image/jpeg',b'cover'))
            shelves.save_shelf(self.key, [], sources)
            self.assertEqual(shelves.cover(self.key,'book:1'), ('image/jpeg',b'cover'))
        self.assertEqual(fetch.call_count,1,'unchanged cover URL should retain its cached image')

    def test_sync_requires_same_origin_custom_header_and_query_encodes_id(self):
        self.assertEqual(self.request('/api/shelf/sync', 'POST')[0], 403)
        self.assertEqual(self.request('/api/shelf/sync', 'POST', {'X-WeRead-Client':'dashboard','Origin':'https://evil.example'})[0], 403)
        status, data = self.request('/api/book/sync?id=book%3A1&part=all', 'POST', self.post_headers())
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_failed_or_upgrade_shelf_sync_preserves_previous_snapshot(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        previous = [{'id':'book:old','kind':'book','title':'旧快照'}]
        shelves.save_shelf(self.key, previous)
        for response in ({'books': [], 'albums': [], 'mp': [], 'upgrade_info': {'v':2}}, {'errcode': 9}):
            with patch('bookshelf.request_api', return_value=response):
                status, _ = self.request('/api/shelf/sync', 'POST', self.post_headers())
            self.assertGreaterEqual(status, 400)
            self.assertEqual(shelves.shelf(self.key)['items'], previous)

    def test_empty_complete_snapshot_replaces_old_and_accounts_are_isolated(self):
        shelves = bookshelf.ShelfStore(self.store.path)
        shelves.save_shelf(self.key, [{'id':'book:old','kind':'book'}])
        with patch('bookshelf.request_api', return_value={'books': [], 'albums': [], 'mp': None}):
            status, response = self.request('/api/shelf/sync', 'POST', self.post_headers())
        self.assertEqual(status, 200); self.assertEqual(response['items'], [])
        shelves.save_shelf('test-key-B', [{'id':'book:private','kind':'book'}])
        with patch('dashboard.load_key', return_value='test-key-B'):
            status, response = self.request('/api/shelf')
        self.assertEqual(status, 200); self.assertEqual(response['items'][0]['id'], 'book:private')
        self.assertNotIn(bookshelf.ShelfStore.namespace('test-key-B'), json.dumps(response))

    def test_demo_isolated_from_key_cache_and_upstream(self):
        demo_server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store, demo=True))
        thread = threading.Thread(target=demo_server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{demo_server.server_port}'
        try:
            with patch('dashboard.load_key', side_effect=AssertionError('demo read key')), patch('bookshelf.request_api', side_effect=AssertionError('demo called upstream')), patch.object(Store, 'read', side_effect=AssertionError('demo read monthly cache')):
                for path, method in (('/api/shelf','GET'),('/api/shelf/sync','POST')):
                    req=urllib.request.Request(url+path,method=method,headers=self.post_headers() if method=='POST' else {})
                    try:
                        with urllib.request.urlopen(req) as response: status=response.status; data=json.load(response)
                    except urllib.error.HTTPError as error:
                        status=error.code; data=json.load(error); error.close()
                    self.assertEqual(status,200,(path,data))
                    self.assertTrue(data['demo'])
                    self.assertTrue(all(item['id'] in {f'book:demo{i}' for i in range(1,6)} | {'album:demo1','articles'} for item in data['items']))
                    self.assertTrue(any(item.get('progress',{}).get('progress') == 100 for item in data['items']))
                req=urllib.request.Request(url+'/api/notes/sync',method='POST',headers=self.post_headers())
                with urllib.request.urlopen(req) as response: notes_sync=json.load(response)
                self.assertEqual(notes_sync['bookCount'],4)
                req=urllib.request.Request(url+'/api/shelf')
                with urllib.request.urlopen(req) as response: updated=json.load(response)
                self.assertEqual(updated['notesSyncedAt'],notes_sync['syncedAt'])
                self.assertEqual(updated['items'][0]['notes'],{'noteCount':2,'reviewCount':1,'bookmarkCount':1,'total':4})
                req=urllib.request.Request(url+'/api/book?id=book%3Ademo1')
                with urllib.request.urlopen(req) as response: detail=json.load(response)
                self.assertEqual(detail['notes'],updated['items'][0]['notes'])
        finally:
            demo_server.shutdown(); demo_server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
