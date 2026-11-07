"""Local-only WeRead dashboard. Python 3.11+, no third-party dependencies."""
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
GATEWAY = 'https://i.weread.qq.com/api/agent/gateway'
SKILL_VERSION = '1.0.5'
LOCK = threading.Lock()


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
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
        self.path.chmod(0o600)

    def read(self):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT data FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def write(self, snapshot):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES (1, ?)', (json.dumps(snapshot, ensure_ascii=False),))


def synchronize(store):
    key = load_key()
    today = datetime.now(TZ).date()
    # Fetch all months into memory before replacing the previous complete snapshot.
    months = [normalize_month(fetch_month(month, key), month, today) for month in month_keys(today)]
    snapshot = build_snapshot(months, datetime.now(TZ).isoformat(timespec='seconds'), False)
    store.write(snapshot)
    return snapshot


def handler_for(store, demo=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Never log request contents or reading data.

        def allowed(self):
            host = self.headers.get('Host', '')
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            return host in hosts and (not origin or origin == f'http://{host}') and self.headers.get('Sec-Fetch-Site') != 'cross-site'

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
            if not self.allowed():
                return self.reply(403, {'error': '仅允许本机同源访问。'})
            if self.path == '/api/dashboard':
                snapshot = demo_snapshot() if demo else store.read()
                return self.reply(200, snapshot or {'months': [], 'demo': False, 'syncedAt': None})
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                name, kind = assets[self.path]
                return self.reply(200, (ROOT / 'web' / name).read_bytes(), kind)
            return self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed() or self.headers.get('X-WeRead-Client') != 'dashboard':
                return self.reply(403, {'error': '仅允许本机页面发起同步。'})
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
