#!/usr/bin/env python3
"""gdproxy.py - tiny local HTTP(S) caching + retrying proxy for Geometry Dash.

Run it on your own machine (it listens on 127.0.0.1 only), then enable the
GD Proxy Helper mod and set Proxy URL to http://127.0.0.1:8080.

What it does:
  * Every request GD makes (levels, lists, music, song info) comes here.
  * GET requests are cached on disk by URL hash - repeat downloads are
    served instantly, so a song that failed the first time the game tried
    it is already on disk the next time.
  * Upstream fetch is retried a few times with backoff, which is what turns
    "first attempt fails, second succeeds" into "first attempt succeeds".
  * HTTPS is forwarded as a raw tunnel (CONNECT) - no MITM, no caching for
    encrypted traffic, it just works.

Usage:
  python gdproxy.py [--port 8080] [--cache gdproxy-cache] [--retries 3]
"""

import argparse
import hashlib
import http.server
import os
import shutil
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

CACHE_DIR = None
RETRIES = 3


def cache_path(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".bin")


def fetch_with_retry(url: str, timeout: int = 30):
    """Fetch URL, retrying on transient errors. Returns (status, headers, body)."""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gdproxy/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return resp.status, dict(resp.headers), body
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504, 429):
                last_err = e
            else:
                # client error: no point retrying
                raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as e:
            last_err = e
        if attempt < RETRIES:
            time.sleep(attempt)  # 1s, 2s, ... backoff
    raise last_err if last_err else RuntimeError("fetch failed")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[gdproxy] %s\n" % (fmt % args))

    # ---- GET: cache + retry ----
    def do_GET(self):
        url = self.path  # GD sends absolute-form URIs through proxies
        if not url.startswith("http"):
            # some clients send origin-form; we do not know the host -> pass through as-is
            url = "http://" + (self.headers.get("Host", "localhost")) + url
        cache = cache_path(url)
        body = None
        ctype = None
        if os.path.exists(cache):
            with open(cache, "rb") as f:
                body = f.read()
            meta = cache + ".type"
            if os.path.exists(meta):
                with open(meta, "r", encoding="utf-8") as f:
                    ctype = f.read().strip()
            self.send_response(200)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            sys.stderr.write("[gdproxy] cache HIT  %s\n" % url)
            return
        try:
            status, headers, fetched = fetch_with_retry(url)
        except Exception as e:
            sys.stderr.write("[gdproxy] FAIL %s: %s\n" % (url, e))
            self.send_response(502)
            msg = b"gdproxy upstream error"
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        ctype = headers.get("Content-Type", "application/octet-stream")
        with open(cache, "wb") as f:
            f.write(fetched)
        with open(cache + ".type", "w", encoding="utf-8") as f:
            f.write(ctype)
        sys.stderr.write("[gdproxy] cache MISS %s (%d bytes)\n" % (url, len(fetched)))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(fetched)))
        self.end_headers()
        self.wfile.write(fetched)

    # ---- POST: pass through, never cache ----
    def do_POST(self):
        self.forward_passthrough("POST")

    # ---- CONNECT: raw TLS tunnel ----
    def do_CONNECT(self):
        try:
            host, port = self.path.rsplit(":", 1)
            port = int(port)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        try:
            up = socket.create_connection((host, port), timeout=30)
        except OSError as e:
            sys.stderr.write("[gdproxy] CONNECT %s failed: %s\n" % (self.path, e))
            self.send_response(502)
            self.end_headers()
            return
        self.send_response(200, "Connection established")
        self.end_headers()
        self.wfile.flush()
        sys.stderr.write("[gdproxy] CONNECT tunnel %s\n" % self.path)
        conn = self.connection

        def pump(src, dst, name):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t1 = threading.Thread(target=pump, args=(conn, up, "c->u"), daemon=True)
        t2 = threading.Thread(target=pump, args=(up, conn, "u->c"), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            up.close()
        except OSError:
            pass

    def forward_passthrough(self, method):
        url = self.path
        if not url.startswith("http"):
            url = "http://" + (self.headers.get("Host", "localhost")) + url
        body = None
        length = self.headers.get("Content-Length")
        if length:
            try:
                body = self.rfile.read(int(length))
            except OSError:
                body = None
        try:
            req = urllib.request.Request(url, data=body, method=method, headers={k: v for k, v in self.headers.items() if k.lower() not in ("proxy-authorization",)})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                status = resp.status
                hdrs = dict(resp.headers)
        except urllib.error.HTTPError as e:
            status = e.code
            data = e.read()
            hdrs = dict(e.headers)
        except Exception as e:
            sys.stderr.write("[gdproxy] %s FAIL %s: %s\n" % (method, url, e))
            self.send_response(502)
            msg = b"gdproxy upstream error"
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        self.send_response(status)
        ct = hdrs.get("Content-Type", "application/octet-stream")
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global CACHE_DIR, RETRIES
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gdproxy-cache"))
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()
    CACHE_DIR = args.cache
    RETRIES = max(1, args.retries)
    os.makedirs(CACHE_DIR, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("gdproxy listening on 127.0.0.1:%d (cache: %s, retries: %d)" % (args.port, CACHE_DIR, RETRIES), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("gdproxy stopped", flush=True)


if __name__ == "__main__":
    main()
