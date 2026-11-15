"""Local-only WeRead dashboard. Python 3.11+, no third-party dependencies."""
import argparse
import calendar
import html
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import bookshelf

def demo_shelf(notes_synced_at=None):
    items=[]
    for i,(title,author,cat,progress,finished) in enumerate([('山野之间','演示作者','文学',1,False),('时间的纹理','演示作者','社会科学',35,False),('日常的发现','演示作者','生活',100,True),('星河旅人','演示作者','科幻',None,None),('远方来信','演示作者','文学',None,False)],1):
        prog={'progress':progress,'recordReadingTime':2400+i*600} if progress is not None else None
        items.append({'id':f'book:demo{i}','kind':'book','bookId':f'demo{i}','title':title,'author':author,'category':cat,'coverPath':f'/api/cover?id=book%3Ademo{i}','readerLink':None,'deepLink':None,'readUpdateTime':int(datetime.now(TZ).timestamp())-i*86400,'finished':finished,'progress':prog,'notes':None})
    items.append({'id':'album:demo1','kind':'album','bookId':None,'title':'山海之间（有声书）','author':'演示播音','category':'有声书','coverPath':'/api/cover?id=album%3Ademo1','readerLink':None,'deepLink':None,'readUpdateTime':None,'finished':None,'progress':None})
    items.append({'id':'articles','kind':'articles','bookId':None,'title':'文章收藏','author':'','category':'文章收藏','coverPath':None,'readerLink':None,'deepLink':None,'readUpdateTime':None,'finished':None,'progress':None})
    if notes_synced_at:
        for item in items:
            if item['kind']=='book': item['notes']={'noteCount':2,'reviewCount':1,'bookmarkCount':1,'total':4}
    return {'items':items,'syncedAt':datetime.now(TZ).isoformat(timespec='seconds'),'demo':True,'notesSyncedAt':notes_synced_at}

def demo_book_payload(bid):
    n=int(bid[9:]) if bid.startswith('book:demo') and bid[9:].isdigit() else 0
    vals={1:1,2:35,3:100,4:None,5:None}; pct=vals.get(n)
    title={1:'山野之间',2:'时间的纹理',3:'日常的发现',4:'星河旅人',5:'远方来信'}.get(n,'演示书目')
    progress=({'progress':pct,'recordReadingTime':3600} if pct is not None else None)
    if pct==100: progress['finishTime']=int(time.time())
    return {'id':bid,'info':{'title':title,'author':'演示作者','intro':'这是本地生成的演示简介。它用于展示详情布局、评分与较长文本的折叠效果，不对应真实书籍或用户数据。\n\n演示数据不会访问密钥、真实缓存或微信读书接口。','publisher':'演示出版社','publishTime':'2026','wordCount':123456,'newRating':870,'newRatingCount':1234},'progress':progress,'notes':None,'infoSyncedAt':None,'progressSyncedAt':None,'notesSyncedAt':None,'errors':[]}

def demo_svg(book_id):
    palette={'demo1':('#245b54','#e6c98f'),'demo2':('#493b72','#f0ca8a'),'demo3':('#9c5738','#f2d69c'),'demo4':('#273f68','#b6d6ed'),'demo5':('#766443','#ecdfc4'),'demoalbum':('#6d3d59','#f1c7a3')}
    bg,fg=palette.get(book_id,('#365b54','#f2d49c'))
    safe=html.escape({'demo1':'山野之间','demo2':'时间的纹理','demo3':'日常的发现','demo4':'星河旅人','demo5':'远方来信','demoalbum':'山海之间'} .get(book_id,'演示书目'))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 440"><rect width="320" height="440" fill="{bg}"/><circle cx="250" cy="80" r="55" fill="{fg}" opacity=".75"/><path d="M0 330 Q80 210 160 330 T320 300 V440 H0Z" fill="{fg}" opacity=".45"/><text x="24" y="375" fill="white" font-size="25" font-family="sans-serif">{safe}</text><text x="24" y="408" fill="white" opacity=".7" font-size="13">WEREAD · DEMO</text></svg>'.encode()

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
GATEWAY = 'https://i.weread.qq.com/api/agent/gateway'
SKILL_VERSION = '1.0.5'
LOCK = threading.Lock()
SHELF_SYNC_LOCKS = {}
SHELF_SYNC_LOCKS_GUARD = threading.Lock()


def load_key():
    key = ''
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip() == 'WEREAD_API_KEY':
                key = value.strip().strip('\"\'')
    key = key or os.environ.get('WEREAD_API_KEY', '').strip()
    if not key:
        raise ValueError('请在 .env 中填写 WEREAD_API_KEY，或先使用演示模式。')
    if not key.startswith('wrk-') or any(c.isspace() for c in key):
        raise ValueError('API key 格式不正确，应以 wrk- 开头且不含空白。')
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_month(month, key):
    base = datetime.fromisoformat(month + '-01').replace(tzinfo=TZ)
    request = urllib.request.Request(GATEWAY, data=json.dumps({
        'api_name': '/readdata/detail', 'mode': 'monthly',
        'baseTime': int(base.timestamp()), 'skill_version': SKILL_VERSION,
    }).encode(), headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'微信读书返回 HTTP {exc.code}，请检查密钥或稍后重试。') from None
    except (urllib.error.URLError, OSError):
        raise ValueError('连接微信读书失败，请检查网络后重试。') from None
    except (ValueError, UnicodeError):
        raise ValueError('微信读书未返回有效 JSON。') from None
    if not isinstance(result, dict):
        raise ValueError('微信读书响应格式异常。')
    if 'upgrade_info' in result:
        # Do not execute instructions or continue syncing with an obsolete version.
        raise ValueError('微信读书要求升级 skill；已停止同步。请更新官方 skill 并核对接口版本后重试。')
    if result.get('errcode', 0) not in (0, '0'):
        raise ValueError('微信读书返回业务错误，请检查密钥权限或稍后重试。')
    return result


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('阅读统计包含无效数值，已停止同步。')
    return value


def normalize_month(raw, month, today):
    start = date.fromisoformat(month + '-01')
    base = datetime.fromtimestamp(raw.get('baseTime', 0), TZ).date()
    if base != start:
        raise ValueError('接口返回的统计周期不匹配，已停止同步。')
    end = min(date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]), today)
    total = numeric(raw.get('totalReadTime'))
    read_days = numeric(raw.get('readDays'))
    buckets = raw.get('readTimes', {})
    if not isinstance(buckets, dict):
        raise ValueError('日明细格式异常。')
    values = {}
    for stamp, seconds in buckets.items():
        day = datetime.fromtimestamp(int(stamp), TZ).date()
        if start <= day <= end:
            if day.isoformat() in values:
                raise ValueError('接口返回重复日明细。')
            values[day.isoformat()] = numeric(seconds)
    days = [{'date': (start + timedelta(days=i)).isoformat(),
             'seconds': values.get((start + timedelta(days=i)).isoformat())}
            for i in range((end - start).days + 1)]
    if read_days > len(days) or int(read_days) != read_days:
        raise ValueError('有效阅读天数超出统计周期。')
    complete = all(d['seconds'] is not None for d in days)
    books = []
    for item in raw.get('readLongest', []):
        book = item.get('book') or item.get('albumInfo') or {}
        books.append({'title': str(book.get('title') or book.get('name') or '未命名内容'),
                      'author': str(book.get('author') or book.get('authorName') or ''),
                      'seconds': numeric(item.get('readTime', 0))})
    return {'month': month, 'days': days, 'totalSeconds': total, 'readDays': read_days,
            'dailyComplete': complete, 'reconciled': complete and abs(sum(values.values()) - total) < 1,
            'books': books}


def month_keys(today, count=12):
    index = today.year * 12 + today.month - 1
    return [f'{i // 12:04}-{i % 12 + 1:02}' for i in range(index - count + 1, index + 1)]


def build_snapshot(months, synced_at, demo):
    return {'months': months, 'syncedAt': synced_at, 'demo': demo,
            'source': {'provider': 'WeRead Agent API', 'endpoint': '/readdata/detail',
                       'mode': 'monthly', 'skillVersion': SKILL_VERSION, 'timezone': 'Asia/Shanghai',
                       'unit': 'seconds', 'effectiveDayThreshold': 60,
                       'totalDefinition': 'totalReadTime（阅读与收听）',
                       'dailyDefinition': 'readTimes；未返回的日期保留为空，不补零',
                       'bookCoverage': '每月最多 10 项；低于 5 分钟的条目可能不返回'}}


def demo_snapshot():
    today = datetime.now(TZ).date()
    months = []
    for index, month in enumerate(month_keys(today)):
        start = date.fromisoformat(month + '-01')
        end = min(date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]), today)
        days = []
        for day in range(1, end.day + 1):
            seconds = 0 if (day + index) % 6 == 0 else int((math.sin(day * 1.7 + index) + 1.3) * 1100 + (day % 4) * 210)
            days.append({'date': f'{month}-{day:02}', 'seconds': seconds})
        total = sum(d['seconds'] for d in days)
        months.append({'month': month, 'days': days, 'totalSeconds': total,
                       'readDays': sum(d['seconds'] >= 60 for d in days), 'dailyComplete': True,
                       'reconciled': True, 'books': [
                           {'title': title, 'author': '演示书目', 'seconds': int(total * share)}
                           for title, share in [('山野之间', .44), ('时间的纹理', .28), ('日常的发现', .18)]]})
    return build_snapshot(months, datetime.now(TZ).isoformat(timespec='seconds'), True)


class Store:
    def __init__(self, directory):
        directory.mkdir(mode=0o700, exist_ok=True)
        self.path = directory / 'reading.sqlite3'
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute('CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
        self.path.chmod(0o600)

    def read(self):
        with closing(sqlite3.connect(self.path)) as db:
            with db: row = db.execute('SELECT data FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def write(self, snapshot):
        with closing(sqlite3.connect(self.path)) as db:
            with db: db.execute('INSERT OR REPLACE INTO snapshot VALUES (1, ?)', (json.dumps(snapshot, ensure_ascii=False),))


def synchronize(store):
    key = load_key()
    today = datetime.now(TZ).date()
    # Fetch all months into memory before replacing the previous complete snapshot.
    months = [normalize_month(fetch_month(month, key), month, today) for month in month_keys(today)]
    snapshot = build_snapshot(months, datetime.now(TZ).isoformat(timespec='seconds'), False)
    store.write(snapshot)
    return snapshot


def handler_for(store, demo=False):
    demo_state={'notes_at':None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Never log request contents or reading data.

        def allowed(self, navigation=False):
            host = self.headers.get('Host', '')
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            same_origin = (not origin or origin == f'http://{host}')
            cross_site_ok = navigation and self.path == '/' and self.headers.get('Sec-Fetch-Mode') == 'navigate' and self.headers.get('Sec-Fetch-Dest') == 'document'
            return host in hosts and same_origin and (self.headers.get('Sec-Fetch-Site') != 'cross-site' or cross_site_ok)

        def reply(self, status, body, content_type='application/json; charset=utf-8'):
            data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed(navigation=True):
                return self.reply(403, {'error': '仅允许本机同源访问。'})
            if self.path == '/api/dashboard':
                snapshot = demo_snapshot() if demo else store.read()
                return self.reply(200, snapshot or {'months': [], 'demo': False, 'syncedAt': None})
            if self.path == '/api/shelf':
                if demo: return self.reply(200, demo_shelf(demo_state['notes_at']))
                try: return self.reply(200, bookshelf.ShelfStore(store.path).shelf(load_key()))
                except ValueError as exc: return self.reply(400, {'error': str(exc)})
            if self.path.startswith('/api/book?'):
                from urllib.parse import parse_qs, urlsplit
                bid = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                if not bid.startswith('book:'): return self.reply(400, {'error': '书籍标识无效。'})
                if demo:
                    if not any(x['id']==bid for x in demo_shelf()['items']): return self.reply(404, {'error':'书籍不存在。'})
                    payload=demo_book_payload(bid)
                    if demo_state['notes_at']: payload['notes']={'noteCount':2,'reviewCount':1,'bookmarkCount':1,'total':4}; payload['notesSyncedAt']=demo_state['notes_at']
                    return self.reply(200, payload)
                try:
                    key=load_key(); shelf_store=bookshelf.ShelfStore(store.path)
                    if not any(x['id']==bid and x['kind']=='book' for x in shelf_store.shelf(key)['items']): return self.reply(404, {'error':'该书不在当前书架。'})
                    return self.reply(200, shelf_store.book(key, bid))
                except ValueError as exc: return self.reply(400, {'error': str(exc)})
            if self.path.startswith('/api/cover?'):
                from urllib.parse import parse_qs, urlsplit
                bid=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                if demo:
                    demo_ids={'book:demo1':'demo1','book:demo2':'demo2','book:demo3':'demo3','book:demo4':'demo4','book:demo5':'demo5','album:demo1':'demoalbum'}
                    key=demo_ids.get(bid)
                    if not key: return self.reply(404, {'error':'封面不存在。'})
                    return self.reply(200,demo_svg(key),'image/svg+xml; charset=utf-8')
                if not bid.startswith(('book:','album:')): return self.reply(404,{'error':'封面不存在。'})
                try:
                    mime,data=bookshelf.ShelfStore(store.path).cover(load_key(),bid)
                    if not data: return self.reply(404,{'error':'封面不存在。'})
                    return self.reply(200,data,mime)
                except Exception: return self.reply(404,{'error':'封面暂不可用。'})
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/shelf.js': ('shelf.js', 'text/javascript; charset=utf-8'),
                      '/shelf.css': ('shelf.css', 'text/css; charset=utf-8'),
                      '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                name, kind = assets[self.path]
                return self.reply(200, (ROOT / 'web' / name).read_bytes(), kind)
            return self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            # Release even if a client disconnects while response headers are sent.
            try:
                self.post()
            finally:
                held = getattr(self, '_held_sync_lock', None)
                if held:
                    self._held_sync_lock = None
                    held.release()

        def post(self):
            if not self.allowed() or self.headers.get('X-WeRead-Client') != 'dashboard':
                return self.reply(403, {'error': '仅允许本机页面发起同步。'})
            if self.path in ('/api/shelf/sync', '/api/notes/sync') or self.path.startswith('/api/book/sync?'):
                if demo:
                    if self.path == '/api/shelf/sync': return self.reply(200, demo_shelf(demo_state['notes_at']))
                    if self.path == '/api/notes/sync':
                        demo_state['notes_at']=datetime.now(TZ).isoformat(timespec='seconds')
                        return self.reply(200, {'syncedAt':demo_state['notes_at'],'bookCount':4})
                    from urllib.parse import parse_qs, urlsplit
                    bid=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                    if not any(x['id']==bid and x['kind']=='book' for x in demo_shelf()['items']): return self.reply(404,{'error':'书籍不存在。'})
                    payload=demo_book_payload(bid)
                    if demo_state['notes_at']: payload['notes']={'noteCount':2,'reviewCount':1,'bookmarkCount':1,'total':4}; payload['notesSyncedAt']=demo_state['notes_at']
                    return self.reply(200,payload)
                try:
                    key = load_key(); shelves = bookshelf.ShelfStore(store.path)
                    if not self.path.startswith('/api/book/sync?'):
                        lock_id=(bookshelf.ShelfStore.namespace(key),self.path)
                        with SHELF_SYNC_LOCKS_GUARD: sync_lock=SHELF_SYNC_LOCKS.setdefault(lock_id,threading.Lock())
                        if not sync_lock.acquire(blocking=False): return self.reply(409,{'error':'该同步正在进行，请稍候。'})
                        self._held_sync_lock=sync_lock
                    if self.path == '/api/shelf/sync':
                        raw = bookshelf.request_api(key, '/shelf/sync')
                        items = bookshelf.normalize_shelf(raw)
                        sources={}
                        for b in raw['books']:
                            if b.get('cover'): sources['book:'+str(b['bookId'])]=str(b['cover'])
                        for a in raw['albums']:
                            x=a['albumInfo']
                            if x.get('cover'): sources['album:'+str(x['albumId'])]=str(x['cover'])
                        shelves.save_shelf(key, items, sources)
                        return self.reply(200, shelves.shelf(key))
                    if self.path == '/api/notes/sync':
                        notes = {}; cursor = None; seen = set(); synced = datetime.now(TZ).isoformat(timespec='seconds')
                        while True:
                            args = {'count': 100}
                            if cursor is not None: args['lastSort'] = cursor
                            raw = bookshelf.request_api(key, '/user/notebooks', **args)
                            rows = raw.get('books')
                            if not isinstance(rows, list): raise ValueError('笔记概览格式异常，已保留旧数据。')
                            for row in rows:
                                if not isinstance(row,dict): raise ValueError('笔记条目格式异常，已保留旧数据。')
                                raw_bid=row.get('bookId')
                                if not isinstance(raw_bid,(str,int)) or isinstance(raw_bid,bool) or not str(raw_bid): raise ValueError('笔记书籍标识格式异常，已保留旧数据。')
                                bid = str(raw_bid)
                                vals = {k: row.get(k) for k in ('noteCount','reviewCount','bookmarkCount')}
                                if not all(isinstance(v,int) and not isinstance(v,bool) and v >= 0 for v in vals.values()): raise ValueError('笔记数量格式异常，已保留旧数据。')
                                notes[bid] = {**vals, 'total':sum(vals.values())}
                            more=raw.get('hasMore')
                            if more not in (0,1,'0','1',False,True): raise ValueError('笔记分页状态缺失或格式异常，已保留旧数据。')
                            if more in (0,'0'): break
                            next_cursor = rows[-1].get('sort') if rows else None
                            if not isinstance(next_cursor, (int,float)) or isinstance(next_cursor,bool) or not math.isfinite(next_cursor) or next_cursor<0 or next_cursor in seen or (cursor is not None and next_cursor>=cursor): raise ValueError('笔记分页游标未严格递减，已保留旧数据。')
                            seen.add(next_cursor); cursor = next_cursor
                        # Commit full, validated overview only after the final page.
                        with closing(sqlite3.connect(store.path)) as db:
                            with db:
                                db.execute('CREATE TABLE IF NOT EXISTS note_sync (ns TEXT PRIMARY KEY, synced TEXT)')
                                ns=shelves.namespace(key)
                                db.execute('UPDATE books SET notes=NULL,notes_at=NULL WHERE ns=?',(ns,))
                                for bid,val in notes.items():
                                    db.execute('INSERT OR IGNORE INTO books(ns,id) VALUES (?,?)',(ns,'book:'+bid))
                                    db.execute('UPDATE books SET notes=?,notes_at=? WHERE ns=? AND id=?',(json.dumps(val,ensure_ascii=False),synced,ns,'book:'+bid))
                                db.execute('INSERT OR REPLACE INTO note_sync VALUES (?,?)',(shelves.namespace(key),synced))
                        return self.reply(200, {'syncedAt': synced, 'bookCount':len(notes)})
                    from urllib.parse import parse_qs, urlsplit
                    q = parse_qs(urlsplit(self.path).query); bid = q.get('id',[''])[0]; part=q.get('part',['all'])[0]
                    if not bid.startswith('book:') or part not in ('all','progress'): return self.reply(400, {'error':'书籍同步参数无效。'})
                    current = shelves.shelf(key)['items']
                    if not any(x['id']==bid and x['kind']=='book' for x in current): return self.reply(404, {'error':'该书不在当前书架。'})
                    data=bookshelf.sync_book(shelves,key,bid,part,q.get('force',['0'])[0]=='1')
                    return self.reply(200,data)
                except ValueError as exc: return self.reply(502, {'error': str(exc)})
                except Exception: return self.reply(500, {'error':'书架同步失败，已保留旧缓存。'})
            if self.path != '/api/sync':
                return self.reply(404, {'error': 'Not found'})
            if demo:
                return self.reply(200, demo_snapshot())
            if not LOCK.acquire(blocking=False):
                return self.reply(409, {'error': '已有同步正在进行，请稍候。'})
            try:
                self.reply(200, synchronize(store))
            except ValueError as exc:
                self.reply(502, {'error': str(exc)})
            except Exception:
                self.reply(500, {'error': '同步失败，已保留上次成功的数据。'})
            finally:
                LOCK.release()
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--demo', action='store_true', help='Synthetic data; never reads key or personal data')
    parser.add_argument('--sync', action='store_true', help='Sync once and exit')
    args = parser.parse_args()
    store = None if args.demo else Store(ROOT / '.local')
    if args.sync:
        try:
            data = demo_snapshot() if args.demo else synchronize(store)
            print(f'同步成功：{len(data["months"])} 个月；{data["syncedAt"]}')
        except ValueError as exc:
            parser.exit(1, str(exc) + '\n')
        return
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(store, args.demo))
    print(f'WeRead Dashboard: http://127.0.0.1:{server.server_port}' + ('（演示数据）' if args.demo else ''), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
