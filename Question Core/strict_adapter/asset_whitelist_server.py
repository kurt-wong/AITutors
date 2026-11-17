# -*- coding: utf-8 -*-
"""C1 静态图源服务：已发布题目题面资产白名单（替换裸 http.server 目录暴露）。

部署层组件（QCORE-STUDENT-PHASE-A-C1）：
  - 请求时按 **(学科, 文件名) 二元组精确匹配** 白名单；只有 <subject>/imgs/<filename>
    三段形态才参与匹配，命中即用白名单条目内受信的 subject/filename 拼路径读文件；
  - 不是「整目录挂载 + 后置过滤」：任何未命中白名单元组的请求在碰盘前即 404，
    服务面=白名单本身，G2A 其余文件（OCR Markdown / OCR-JSONL / 答案资产 /
    未引用图片 / 目录列举 / 路径穿越 / 跨学科同名）一律不可达；
  - storage_path 与 content_hash 保持 DB 既有绑定原样使用，不改 DB/Manifest/Adapter；
  - 仅 GET/HEAD；不提供目录列表。

运行：
  python asset_whitelist_server.py --allowlist <asset_allowlist.json> \
      --root <G2A ocr 目录> --port 8812 [--access-log <log>]
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}


def _parse_key(raw_path: str):
    """请求路径 → (学科, 文件名) 二元组；仅接受 <subject>/imgs/<filename> 三段形态。

    严格规范匹配：分隔符必须是字面 `/`（%2f/%5c 一律拒绝，杜绝解码歧义）；
    先按字面 / 切段、再逐段解码；任何段解码后含 / \\ NUL 或为 . .. 均拒绝。
    精确匹配发生在碰盘之前。
    """
    if "\x00" in raw_path or "\\" in raw_path:
        return None
    split = urlsplit(raw_path)
    raw = split.path
    lowered = raw.lower()
    if "%2f" in lowered or "%5c" in lowered:
        return None  # 编码分隔符不参与匹配
    if "\x00" in raw or "\\" in raw:
        return None
    segs = [s for s in raw.split("/") if s != ""]
    if len(segs) != 3:
        return None
    decoded = []
    for s in segs:
        try:
            d = unquote(s, errors="strict")
        except Exception:
            return None
        if "/" in d or "\\" in d or "\x00" in d or d in (".", ".."):
            return None
        decoded.append(d)
    subject, mid, filename = decoded
    if mid != "imgs":
        return None
    return subject, filename


class WhitelistHandler(BaseHTTPRequestHandler):
    server_version = "QcoreAssetWhitelist/1.0"
    allowlist: dict = {}  # (subject, filename) -> entry；请求时二元组精确匹配
    root: Path = Path(".")
    access_log = None

    def log_message(self, fmt, *args):  # 静默默认 stderr 日志，改走显式 access log
        self._log(f"{self.address_string()} {fmt % args}")

    def _log(self, line: str) -> None:
        if self.access_log:
            try:
                with open(self.access_log, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def _deny(self, note: str) -> None:
        self._log(f"DENY {self.command} {self.path!r} ({note})")
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _serve(self) -> None:
        key = _parse_key(self.path)
        if key is None:
            return self._deny("not <subject>/imgs/<filename> form")
        entry = self.allowlist.get(key)  # (学科, 文件名) 二元组精确匹配
        if entry is None:
            return self._deny("allowlist miss for (subject, filename)")
        # 用白名单内受信 subject/filename 拼路径（不用请求串碰盘）
        subject, filename = key
        target = (self.root / subject / "imgs" / filename).resolve()
        try:
            target.relative_to(self.root.resolve())
        except ValueError:
            return self._deny("resolved outside root")
        if not target.is_file():
            return self._deny("allowlisted file missing on disk")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", entry.get("mime_type") or _MIME.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        self._log(f"ALLOW {self.command} {subject}/imgs/{filename} {entry['sample']} {entry['asset_id']} bytes={len(data)}")

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def do_POST(self):
        self._deny("method not allowed")

    def do_PUT(self):
        self._deny("method not allowed")

    def do_DELETE(self):
        self._deny("method not allowed")

    def do_OPTIONS(self):
        self._deny("method not allowed")

    def do_PATCH(self):
        self._deny("method not allowed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=8812)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--access-log", default=None)
    args = ap.parse_args()

    doc = json.loads(Path(args.allowlist).read_text(encoding="utf-8"))
    entries = doc["allowlist"]
    table = {}
    for e in entries:
        key = (e["subject"], e["filename"])
        expected = f"{e['subject']}/imgs/{e['filename']}"
        if e.get("url_path") != expected:
            raise SystemExit(f"FAIL-CLOSED: url_path mismatch in allowlist entry: {e}")
        if key in table:
            raise SystemExit(f"FAIL-CLOSED: duplicate (subject, filename) in allowlist: {key}")
        if not e.get("storage_path", "").startswith("_imgs/"):
            raise SystemExit(f"FAIL-CLOSED: storage_path binding broken: {e}")
        if not e.get("content_hash"):
            raise SystemExit(f"FAIL-CLOSED: content_hash binding missing: {e}")
        table[key] = e

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"FAIL-CLOSED: root not a directory: {root}")
    for e in entries:
        p = root / e["subject"] / "imgs" / e["filename"]
        if not p.is_file():
            raise SystemExit(f"FAIL-CLOSED: allowlisted file missing: {p}")

    WhitelistHandler.allowlist = table
    WhitelistHandler.root = root
    WhitelistHandler.access_log = args.access_log

    httpd = ThreadingHTTPServer((args.bind, args.port), WhitelistHandler)
    print(f"qcore-asset-whitelist on http://{args.bind}:{args.port}  root={root}")
    print(f"allowlist entries={len(table)} (request-time exact match on (subject, filename) pairs)")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
