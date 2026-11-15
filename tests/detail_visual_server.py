#!/usr/bin/env python3
"""Local-only visual timing harness backed exclusively by dashboard demo data.

Example:
  python3 tests/detail_visual_server.py --port 8777 --get-delay-ms 300 \
    --sync-delay-ms 1500 --long-intro --long-title --slow-motion 2

Open the printed URL, click a book, then read
document.getElementById('detail-visual-samples').textContent in the browser.
No personal cache, API key, upstream service, or product debug route is used.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import dashboard


PROBE_JS = r'''(() => {
  const params = new URLSearchParams(location.search);
  const slow = Math.max(1, Number(params.get('slow') || 1));
  if (slow > 1 && Element.prototype.animate) {
    const nativeAnimate = Element.prototype.animate;
    Element.prototype.animate = function (frames, options = {}) {
      const next = typeof options === 'number' ? { duration: options * slow } : { ...options, duration: (options.duration || 0) * slow };
      return nativeAnimate.call(this, frames, next);
    };
  }
  const output = document.createElement('pre');
  output.id = 'detail-visual-samples';
  output.hidden = true;
  output.setAttribute('aria-hidden', 'true');
  document.body.append(output);
  const samples = [];
  let observer, generation = 0;
  const stage = () => {
    const body = document.getElementById('detail-body');
    if (!body) return 'no-detail';
    const text = body.textContent || '';
    if (text.includes('FRESH INTRO')) return 'fresh-data';
    if (text.includes('CACHE INTRO')) return 'cached-data';
    if (/读取|加载中|加载简介/.test(text)) return 'loading';
    if (/暂无简介|推荐值|笔记/.test(text)) return 'detail-content';
    return 'empty';
  };
  const geometry = phase => {
    const root = document.documentElement;
    const rect = selector => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const r = node.getBoundingClientRect();
      return { left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height };
    };
    const dialog = document.getElementById('book-dialog');
    const frame = dialog?.querySelector('.detail-frame') || dialog?.querySelector('.detail-sheet');
    const close = document.getElementById('detail-close');
    const c = close?.getBoundingClientRect();
    const r = frame?.getBoundingClientRect();
    const cs = frame ? getComputedStyle(frame) : null;
    const body = document.getElementById('detail-body');
    return {
      phase, time: Math.round(performance.now()), rootClientWidth: root.clientWidth,
      innerWidth: window.innerWidth, gutter: window.innerWidth - root.clientWidth,
      body: rect('body'), main: rect('main'), heading: rect('.shelf-heading, .page-heading'),
      bookWall: rect('#book-wall'), brand: rect('.brand'),
      card: r ? { left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:frame.offsetWidth, height:frame.offsetHeight,
        centerX:(r.left+r.right)/2, centerY:(r.top+r.bottom)/2, opacity:cs.opacity, transform:cs.transform } : null,
      close: c ? { left:c.left, top:c.top, right:c.right, bottom:c.bottom } : null,
      pageY: window.scrollY, stage: stage(), bodyTextLength: body?.textContent.length || 0,
      introText: (document.querySelector('#detail-body section p')?.textContent || '').slice(0, 100)
    };
  };
  const write = sample => { samples.push(sample); output.textContent = JSON.stringify(samples); };
  const sampleOpen = (start, id) => {
    if (id !== generation || !document.getElementById('book-dialog')?.open) return;
    write({ ...geometry('open'), elapsed: Math.round(performance.now() - start) });
    if (performance.now() - start < 6000) requestAnimationFrame(() => sampleOpen(start, id));
  };
  const sampleClosed = (start, id) => {
    if (id !== generation) return;
    write({ ...geometry('closed'), elapsed: Math.round(performance.now() - start) });
    if (performance.now() - start < 1500) requestAnimationFrame(() => sampleClosed(start, id));
  };
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-book-id]')) return;
    samples.length = 0;
    const id = ++generation;
    const start = performance.now();
    write(geometry('before-open'));
    if (observer) observer.disconnect();
    observer = new MutationObserver(() => { output.dataset.stage = stage(); });
    observer.observe(document.getElementById('detail-body') || document.body, { childList: true, subtree: true, characterData: true });
    requestAnimationFrame(() => sampleOpen(start, id));
  }, true);
  document.getElementById('book-dialog')?.addEventListener('close', () => {
    const id = ++generation;
    const start = performance.now();
    requestAnimationFrame(() => sampleClosed(start, id));
  });
})();
'''

PROBE_CSS = {
    'classic': '::-webkit-scrollbar { width: 16px; height: 16px; }\n',
    'zero': '::-webkit-scrollbar { width: 0; height: 0; }\n',
}


def build_server(port: int, get_delay_ms: int, sync_delay_ms: int,
                 long_intro: bool, long_title: bool, slow_motion: float,
                 baseline_ref: str | None = None, fail_sync_once: bool = False,
                 classic_scrollbar: bool = False, zero_scrollbar: bool = False):
    # handler_for(None, demo=True) bypasses Store, key loading, and upstream API.
    base = dashboard.handler_for(None, demo=True)
    original_shelf = dashboard.demo_shelf
    original_payload = dashboard.demo_book_payload
    phase = threading.local()

    def demo_shelf(*args, **kwargs):
        result = original_shelf(*args, **kwargs)
        if long_title:
            for item in result['items']:
                if item['id'] == 'book:demo1':
                    item['title'] = '长标题演示：' + '固定卡片定位与内容稳定性验证 ' * 5
        return result

    def demo_book_payload(book_id):
        payload = original_payload(book_id)
        if long_intro and book_id == 'book:demo1':
            marker = 'FRESH INTRO' if getattr(phase, 'fresh', False) else 'CACHE INTRO'
            paragraph = (marker + '：这是一段虚构的长简介，用于验证详情卡固定外框、内部滚动和异步内容更新时的位置稳定性。')
            payload.setdefault('info', {})['intro'] = paragraph * (30 if getattr(phase, 'fresh', False) else 3)
        return payload

    dashboard.demo_shelf = demo_shelf
    dashboard.demo_book_payload = demo_book_payload
    failure_lock = threading.Lock()
    failure_pending = [fail_sync_once]
    baseline_assets = {}
    if baseline_ref:
        for name in ('index.html', 'shelf.js', 'shelf.css', 'styles.css', 'app.js'):
            baseline_assets['/' if name == 'index.html' else f'/{name}'] = subprocess.run(
                ['git', 'show', f'{baseline_ref}:web/{name}'], cwd=dashboard.ROOT,
                check=True, capture_output=True).stdout

    class ProbeHandler(base):
        def do_GET(self):
            route = urlsplit(self.path).path
            if route == '/__detail_probe.js':
                return self.reply(200, PROBE_JS.encode(), 'text/javascript; charset=utf-8')
            if route == '/__detail_probe.css' and (classic_scrollbar or zero_scrollbar):
                mode = 'classic' if classic_scrollbar else 'zero'
                return self.reply(200, PROBE_CSS[mode].encode(), 'text/css; charset=utf-8')
            if route == '/':
                original_path = self.path
                self.path = '/'
                allowed = self.allowed(navigation=True)
                self.path = original_path
                if not allowed:
                    return self.reply(403, {'error': '仅允许本机同源访问。'})
                html = baseline_assets.get('/', (dashboard.ROOT / 'web' / 'index.html').read_bytes()).decode('utf-8')
                html = html.replace('<script defer src="/shelf.js"></script>',
                                    '<script defer src="/__detail_probe.js"></script><script defer src="/shelf.js"></script>')
                if classic_scrollbar or zero_scrollbar:
                    html = html.replace('</head>', '<link rel="stylesheet" href="/__detail_probe.css"></head>')
                return self.reply(200, html.encode(), 'text/html; charset=utf-8')
            if route in baseline_assets and route != '/':
                kind = 'text/javascript; charset=utf-8' if route.endswith('.js') else 'text/css; charset=utf-8'
                return self.reply(200, baseline_assets[route], kind)
            if self.path.startswith('/api/book?'):
                time.sleep(get_delay_ms / 1000)
                phase.fresh = False
            return super().do_GET()

        def do_POST(self):
            if self.path.startswith('/api/book/sync?'):
                time.sleep(sync_delay_ms / 1000)
                phase.fresh = True
            return super().do_POST()

        def post(self):
            if self.path.startswith('/api/book/sync?') and 'part=all' in self.path:
                authorized = self.allowed() and self.headers.get('X-WeRead-Client') == 'dashboard'
                if authorized:
                    with failure_lock:
                        fail_now = failure_pending[0]
                        failure_pending[0] = False
                    if fail_now:
                        return self.reply(503, {'error': '诊断模式：首次详情同步故意失败，请重试。'})
            return super().post()

    return ThreadingHTTPServer(('127.0.0.1', port), ProbeHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8777)
    parser.add_argument('--get-delay-ms', type=int, default=0, help='delay cached detail GET (0, 300, 1500)')
    parser.add_argument('--sync-delay-ms', type=int, default=0, help='delay background detail sync (0, 300, 1500)')
    parser.add_argument('--long-intro', action='store_true', help='serve a long fictional book intro')
    parser.add_argument('--long-title', action='store_true', help='serve a long fictional book title')
    parser.add_argument('--slow-motion', type=float, default=1, help='multiply Element.animate durations in test page only')
    parser.add_argument('--baseline-ref', choices=('c05d550', '567b3dc'), help='serve only a fixed baseline web UI revision')
    parser.add_argument('--fail-sync-once', action='store_true', help='first authorized part=all sync returns 503; retry succeeds')
    parser.add_argument('--classic-scrollbar', action='store_true', help='inject a 16px WebKit scrollbar rule into this diagnostic page only')
    parser.add_argument('--zero-scrollbar', action='store_true', help='simulate a zero-width WebKit scrollbar on this diagnostic page only; not an OS overlay-scrollbar test')
    args = parser.parse_args()
    if min(args.get_delay_ms, args.sync_delay_ms) < 0 or args.slow_motion < 1:
        parser.error('delays must be non-negative and slow-motion must be at least 1')
    if args.classic_scrollbar and args.zero_scrollbar:
        parser.error('--classic-scrollbar and --zero-scrollbar are mutually exclusive')
    server = build_server(args.port, args.get_delay_ms, args.sync_delay_ms,
                          args.long_intro, args.long_title, args.slow_motion, args.baseline_ref,
                          args.fail_sync_once, args.classic_scrollbar, args.zero_scrollbar)
    print(f'Detail visual demo: http://127.0.0.1:{server.server_port}/?slow={args.slow_motion} (fictional data only)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
