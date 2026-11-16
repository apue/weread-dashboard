"""Private, account-scoped bookshelf cache and WeRead response normalization."""
import hashlib
from contextlib import closing
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

GATEWAY = 'https://i.weread.qq.com/api/agent/gateway'
SKILL_VERSION = '1.0.5'
INFO_FIELDS = ('title', 'author', 'intro', 'publisher', 'publishTime', 'wordCount', 'newRating', 'newRatingCount', 'readerLink', 'deepLink')
PROGRESS_FIELDS = ('progress', 'chapterUid', 'chapterOffset', 'updateTime', 'recordReadingTime', 'finishTime')
_locks_guard = threading.Lock()
_book_locks = {}
_cover_guard = threading.Lock()
_cover_locks = {}
ALLOWED_COVER_HOSTS = {'cdn.weread.qq.com', 'res.weread.qq.com', 'weread-1258476243.file.myqcloud.com', 'weread-epub-1258476243.file.myqcloud.com', 'wfqqreader-1252317822.image.myqcloud.com'}
MAX_COVER_BYTES = 5 * 1024 * 1024


@contextmanager
def connection(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


def safe_link(value):
    if not isinstance(value, str): return None
    p = urlparse(value)
    if p.scheme == 'https' and p.hostname in {'weread.qq.com', 'i.weread.qq.com'}: return value
    if p.scheme == 'weread' and p.netloc: return value
    return None


def validate_shelf(raw):
    if not isinstance(raw, dict) or 'upgrade_info' in raw:
        raise ValueError('书架响应异常或要求升级；已保留旧书架。')
    if raw.get('errcode', 0) not in (0, '0'):
        raise ValueError('微信读书返回书架业务错误。')
    if not all(k in raw for k in ('books', 'albums', 'mp')) or not isinstance(raw['books'], list) or not isinstance(raw['albums'], list):
        raise ValueError('书架不是完整快照；已保留旧书架。')
    if raw['mp'] is not None and not isinstance(raw['mp'], (dict, list, str)):
        raise ValueError('文章收藏入口格式异常。')
    seen=set()
    for item in raw['books']:
        if not isinstance(item, dict) or not isinstance(item.get('bookId'), (str,int)) or isinstance(item.get('bookId'),bool) or not str(item['bookId']): raise ValueError('电子书条目格式异常。')
        ident='book:'+str(item['bookId'])
        if ident in seen: raise ValueError('书架包含重复条目；已保留旧书架。')
        seen.add(ident)
        stamp=item.get('readUpdateTime')
        if stamp is not None and (not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or not math.isfinite(stamp) or stamp<0): raise ValueError('电子书时间字段格式异常。')
        finished=item.get('finishReading')
        if finished is not None and (isinstance(finished,bool) or finished not in (0,1)): raise ValueError('电子书完读字段格式异常。')
        if item.get('cover') is not None and not isinstance(item['cover'],str): raise ValueError('封面字段格式异常。')
    for item in raw['albums']:
        info=item.get('albumInfo') if isinstance(item,dict) else None
        if not isinstance(info,dict) or not isinstance(info.get('albumId'),(str,int)) or isinstance(info.get('albumId'),bool) or not str(info['albumId']): raise ValueError('有声书条目格式异常。')
        ident='album:'+str(info['albumId'])
        if ident in seen: raise ValueError('书架包含重复条目；已保留旧书架。')
        seen.add(ident)
        extra=item.get('albumInfoExtra',{})
        if extra is not None and not isinstance(extra,dict): raise ValueError('专辑扩展字段格式异常。')
        stamp=(extra or {}).get('lectureReadUpdateTime')
        if stamp is not None and (not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or not math.isfinite(stamp) or stamp<0): raise ValueError('有声书时间字段格式异常。')
        if info.get('cover') is not None and not isinstance(info['cover'],str): raise ValueError('封面字段格式异常。')
    return raw


def normalize_shelf(raw):
    validate_shelf(raw)
    out = []
    for b in raw['books']:
        bid = str(b['bookId'])
        out.append({'id': 'book:' + bid, 'kind': 'book', 'bookId': bid, 'title': str(b.get('title') or '未命名内容'), 'author': str(b.get('author') or ''), 'category': str(b.get('category') or '未分类'), 'coverPath': '/api/cover?id='+quote('book:'+bid,safe='') if b.get('cover') else None, 'readerLink': safe_link(b.get('readerLink')), 'deepLink': safe_link(b.get('deepLink')), 'readUpdateTime': b.get('readUpdateTime') if isinstance(b.get('readUpdateTime'), (int, float)) else None, 'finished': True if b.get('finishReading') == 1 else (False if b.get('finishReading') == 0 else None), 'progress': None})
    for a in raw['albums']:
        x = a['albumInfo']; aid = str(x['albumId']); extra = a.get('albumInfoExtra') or {}
        out.append({'id': 'album:' + aid, 'kind': 'album', 'bookId': None, 'title': str(x.get('name') or '未命名专辑'), 'author': str(x.get('authorName') or ''), 'category': '有声书', 'coverPath': '/api/cover?id='+quote('album:'+aid,safe='') if x.get('cover') else None, 'readerLink': None, 'deepLink': None, 'readUpdateTime': extra.get('lectureReadUpdateTime'), 'finished': None, 'progress': None})
    if raw.get('mp'):
        out.append({'id': 'articles', 'kind': 'articles', 'bookId': None, 'title': '文章收藏', 'author': '', 'category': '文章收藏', 'coverPath': None, 'readerLink': None, 'deepLink': None, 'readUpdateTime': None, 'finished': None, 'progress': None})
    return out


def request_api(key, api_name, **params):
    payload = {'api_name': api_name, 'skill_version': SKILL_VERSION, **params}
    req = urllib.request.Request(GATEWAY, data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=25) as resp: raw = json.load(resp)
    except Exception: raise ValueError('连接微信读书失败。') from None
    if isinstance(raw, dict) and 'upgrade_info' in raw: raise UpgradeRequired('微信读书要求升级；已停止本轮同步。')
    if not isinstance(raw, dict): raise ValueError('微信读书响应格式异常。')
    if raw.get('errcode', 0) not in (0, '0'): raise ValueError('微信读书返回业务错误。')
    return raw


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


class UpgradeRequired(ValueError):
    pass


def fetch_cover(url):
    parsed=urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_COVER_HOSTS or parsed.port not in (None,443) or parsed.username or parsed.password:
        raise ValueError('封面地址不在允许范围。')
    req=urllib.request.Request(url, headers={'Accept':'image/jpeg,image/png,image/webp,image/gif'})
    with urllib.request.build_opener(_NoRedirect).open(req,timeout=8) as response:
        mime=response.headers.get_content_type().lower()
        if mime not in ('image/jpeg','image/png','image/webp','image/gif'): raise ValueError('封面格式不受支持。')
        length=response.headers.get('Content-Length')
        if length and int(length)>MAX_COVER_BYTES: raise ValueError('封面文件过大。')
        data=response.read(MAX_COVER_BYTES+1)
        if not data or len(data)>MAX_COVER_BYTES: raise ValueError('封面文件过大或为空。')
        return mime,data


def sync_book(store,key,bid,part='all',force=False):
    """Serialize a per-book refresh; successful parts commit independently."""
    ns=store.namespace(key)
    with _locks_guard: lock=_book_locks.setdefault((ns,bid),threading.Lock())
    with lock:
        cached=store.book(key,bid)
        def fresh(field, ttl):
            stamp=cached[field+'SyncedAt']
            try: return stamp and time.time()-datetime.fromisoformat(stamp).timestamp()<ttl
            except (ValueError,TypeError): return False
        want_info=part=='all'
        if not force and (not want_info or fresh('info',900)) and fresh('progress',300): return cached
        errors=[]
        if want_info and (force or not fresh('info',900)):
            try:
                raw=request_api(key,'/book/info',bookId=bid[5:])
                info={k:raw[k] for k in INFO_FIELDS if k in raw}
                if not info: raise ValueError('书籍详情为空。')
                for field in ('readerLink','deepLink'):
                    if field in info: info[field]=safe_link(info[field])
                store.save_book_part(key,bid,'info',info)
            except UpgradeRequired: raise
            except Exception as exc: errors.append(str(exc))
        if force or not fresh('progress',300):
            try:
                raw=request_api(key,'/book/getprogress',bookId=bid[5:]); book=raw.get('book')
                if not isinstance(book,dict) or not book: raise ValueError('阅读进度格式异常。')
                progress={k:book[k] for k in PROGRESS_FIELDS if k in book}
                if 'progress' not in progress or not isinstance(progress['progress'],int) or isinstance(progress['progress'],bool) or not 0<=progress['progress']<=100: raise ValueError('阅读进度格式异常。')
                store.save_book_part(key,bid,'progress',progress)
            except UpgradeRequired: raise
            except Exception as exc: errors.append(str(exc))
        result=store.book(key,bid); result['errors']=errors
        return result


class ShelfStore:
    def __init__(self, path):
        self.path = str(path)
        with connection(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS shelves (ns TEXT PRIMARY KEY, items TEXT NOT NULL, synced TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS books (ns TEXT, id TEXT, info TEXT, progress TEXT, notes TEXT, info_at TEXT, progress_at TEXT, notes_at TEXT, PRIMARY KEY(ns,id))')
            db.execute('CREATE TABLE IF NOT EXISTS covers (ns TEXT, id TEXT, url TEXT, mime TEXT, data BLOB, PRIMARY KEY(ns,id))')
            db.execute('CREATE TABLE IF NOT EXISTS cover_sources (ns TEXT, id TEXT, url TEXT, PRIMARY KEY(ns,id))')
    @staticmethod
    def namespace(key): return hashlib.sha256(key.encode()).hexdigest()
    def shelf(self, key):
        with connection(self.path) as db: row=db.execute('SELECT items,synced FROM shelves WHERE ns=?',(self.namespace(key),)).fetchone()
        with connection(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS note_sync (ns TEXT PRIMARY KEY, synced TEXT)')
            nr=db.execute('SELECT synced FROM note_sync WHERE ns=?',(self.namespace(key),)).fetchone()
            books={r[0]:(r[1],r[2]) for r in db.execute('SELECT id,progress,notes FROM books WHERE ns=?',(self.namespace(key),)).fetchall()}
        items=json.loads(row[0]) if row else []
        for item in items:
            cached=books.get(item['id'])
            if cached:
                if cached[0]: item['progress']=json.loads(cached[0])
                if cached[1]: item['notes']=json.loads(cached[1])
                elif nr: item['notes']={'noteCount':0,'reviewCount':0,'bookmarkCount':0,'total':0}
            elif nr and item.get('kind')=='book': item['notes']={'noteCount':0,'reviewCount':0,'bookmarkCount':0,'total':0}
        return {'items': items, 'syncedAt': row[1] if row else None, 'demo': False, 'notesSyncedAt': nr[0] if nr else None}
    def save_shelf(self,key,items,sources=None):
        ns=self.namespace(key)
        with connection(self.path) as db:
            db.execute('INSERT OR REPLACE INTO shelves VALUES (?,?,?)',(ns,json.dumps(items,ensure_ascii=False),time.strftime('%Y-%m-%dT%H:%M:%S%z')))
            if sources is not None:
                old=dict(db.execute('SELECT id,url FROM cover_sources WHERE ns=?',(ns,)).fetchall())
                for cover_id,old_url in old.items():
                    if sources.get(cover_id)!=old_url: db.execute('DELETE FROM covers WHERE ns=? AND id=?',(ns,cover_id))
                db.execute('DELETE FROM cover_sources WHERE ns=?',(ns,))
                for cover_id,url in sources.items(): db.execute('INSERT INTO cover_sources VALUES (?,?,?)',(ns,cover_id,url))
    def cover(self,key,bid):
        ns=self.namespace(key)
        with connection(self.path) as db:
            row=db.execute('SELECT url FROM cover_sources WHERE ns=? AND id=?',(ns,bid)).fetchone()
            cached=db.execute('SELECT url,mime,data FROM covers WHERE ns=? AND id=?',(ns,bid)).fetchone()
        if not row: return None
        url=row[0]; urlhash=hashlib.sha256(url.encode()).hexdigest()
        cache_path=Path(self.path).parent/'covers'/ns/urlhash[:2]/(urlhash+'.img')
        if cached and cached[0]==urlhash and cache_path.is_file(): return cached[1],cache_path.read_bytes()
        with _cover_guard: lock=_cover_locks.setdefault((ns,urlhash),threading.Lock())
        with lock:
            with connection(self.path) as db:
                cached=db.execute('SELECT url,mime,data FROM covers WHERE ns=? AND id=?',(ns,bid)).fetchone()
            if cached and cached[0]==urlhash and cache_path.is_file(): return cached[1],cache_path.read_bytes()
            # Another shelf item with the same upstream URL may have populated the content-addressed file.
            with connection(self.path) as db:
                shared=db.execute('SELECT mime FROM covers WHERE ns=? AND url=? LIMIT 1',(ns,urlhash)).fetchone()
            if shared and cache_path.is_file():
                with connection(self.path) as db: db.execute('INSERT OR REPLACE INTO covers(ns,id,url,mime,data) VALUES (?,?,?,?,NULL)',(ns,bid,urlhash,shared[0]))
                return shared[0],cache_path.read_bytes()
            mime,data=fetch_cover(url)
            cache_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            temp=cache_path.with_suffix('.tmp')
            temp.write_bytes(data); temp.replace(cache_path); cache_path.chmod(0o600)
            with connection(self.path) as db: db.execute('INSERT OR REPLACE INTO covers(ns,id,url,mime,data) VALUES (?,?,?,?,NULL)',(ns,bid,urlhash,mime))
            return mime,data
    def book(self,key,bid):
        with connection(self.path) as db:
            row=db.execute('SELECT info,progress,notes,info_at,progress_at,notes_at FROM books WHERE ns=? AND id=?',(self.namespace(key),bid)).fetchone()
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note_sync'").fetchone()
            complete=db.execute('SELECT synced FROM note_sync WHERE ns=?',(self.namespace(key),)).fetchone() if exists else None
        notes=json.loads(row[2]) if row and row[2] else ({'noteCount':0,'reviewCount':0,'bookmarkCount':0,'total':0} if complete else None)
        return dict(id=bid,info=json.loads(row[0]) if row and row[0] else None,progress=json.loads(row[1]) if row and row[1] else None,notes=notes,infoSyncedAt=row[3] if row else None,progressSyncedAt=row[4] if row else None,notesSyncedAt=row[5] if row and row[5] else (complete[0] if complete else None),errors=[])
    def save_book_part(self,key,bid,part,value):
        col={'info':('info','info_at'),'progress':('progress','progress_at'),'notes':('notes','notes_at')}[part]
        now=time.strftime('%Y-%m-%dT%H:%M:%S%z')
        with connection(self.path) as db:
            db.execute('INSERT OR IGNORE INTO books(ns,id) VALUES (?,?)',(self.namespace(key),bid))
            db.execute(f'UPDATE books SET {col[0]}=?,{col[1]}=? WHERE ns=? AND id=?',(json.dumps(value,ensure_ascii=False),now,self.namespace(key),bid))
