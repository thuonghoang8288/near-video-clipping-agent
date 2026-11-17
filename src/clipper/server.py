"""Tiny HTTP API (Python stdlib only — no web framework needed).

Endpoints:
  GET  /health            -> {"ok": true}
  POST /clip             -> {"job_id": ...}  (JSON body; runs in background)
  GET  /jobs/{id}        -> status + manifest + file list
  GET  /jobs/{id}/files/{name} -> download a clip / srt / report

POST /clip body:
  {
    "source_url": "https://.../video.mp4",   // direct public media URL
    "clips": 5,                                // default 5, max 10
    "formats": ["vertical"],                   // vertical | square | landscape
    "captions": true,
    "language": "en"                           // optional, auto-detect default
  }
Only direct media URLs are fetched (no login-gated sources, no YouTube
page URLs — those need a downloader the agent does not bundle).
Jobs and outputs live under OUT_DIR/<job_id>/.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .pipeline import run

OUT_DIR = os.environ.get("CLIPPER_OUT", "out")
MAX_CLIPS = 10
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

JOBS: dict = {}
LOCK = threading.Lock()


def _new_job_id() -> str:
    return hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:12]


def _fetch_source(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "clipper-agent/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise ValueError("source larger than 2 GB")
            fh.write(chunk)


def _worker(job_id: str, source_path: str, clips: int, formats: list,
            captions: bool, language: str | None) -> None:
    out = os.path.join(OUT_DIR, job_id)
    try:
        manifest = run(source_path, out, clip_count=clips,
                       formats=tuple(formats), captions=captions,
                       language=language)
        with LOCK:
            JOBS[job_id].update({"status": "done", "manifest": manifest})
    except Exception as exc:  # noqa: BLE001 - surfaced in job status
        with LOCK:
            JOBS[job_id].update({"status": "error", "error": str(exc)})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep logs quiet
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True})
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "jobs":
            job_id = parts[1]
            with LOCK:
                job = JOBS.get(job_id)
            if not job:
                return self._json(404, {"error": "unknown job"})
            if len(parts) == 2:
                return self._json(200, job)
            if len(parts) == 4 and parts[2] == "files":
                name = parts[3].replace("/", "").replace("..", "")
                path = os.path.join(OUT_DIR, job_id, name)
                if not os.path.isfile(path):
                    return self._json(404, {"error": "unknown file"})
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(path)))
                self.end_headers()
                with open(path, "rb") as fh:
                    while (chunk := fh.read(1 << 20)):
                        self.wfile.write(chunk)
                return
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/clip":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "invalid JSON"})
        url = body.get("source_url", "")
        if not urlparse(url).scheme.startswith("http"):
            return self._json(400, {"error": "source_url must be a public http(s) URL"})
        clips = int(body.get("clips", 5))
        if not 1 <= clips <= MAX_CLIPS:
            return self._json(400, {"error": "clips must be 1..10"})
        formats = body.get("formats", ["vertical"])
        if not formats or any(f not in ("vertical", "square", "landscape") for f in formats):
            return self._json(400, {"error": "bad formats"})
        job_id = _new_job_id()
        job_dir = os.path.join(OUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        with LOCK:
            JOBS[job_id] = {"job_id": job_id, "status": "fetching",
                            "source_url": url}
        src_path = os.path.join(job_dir, "source" + os.path.splitext(urlparse(url).path)[1][:5])
        try:
            _fetch_source(url, src_path)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                JOBS[job_id].update({"status": "error", "error": f"fetch failed: {exc}"})
            return self._json(200, {"job_id": job_id, "status": "error"})
        with LOCK:
            JOBS[job_id]["status"] = "running"
        threading.Thread(target=_worker, args=(
            job_id, src_path, clips, formats,
            bool(body.get("captions", True)), body.get("language"),
        ), daemon=True).start()
        return self._json(202, {"job_id": job_id, "status": "running"})


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"clipper API on http://{host}:{port} (out dir: {OUT_DIR})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8080)
