"""Tiny HTTP API (Python stdlib only — no web framework needed).

Endpoints:
  GET  /health            -> {"ok": true}
  POST /clip             -> {"job_id": ...}  (JSON body; runs in background)
  POST /clip-sync        -> manifest JSON when done (runs inline; for
                            Cloud Run, whose CPU is throttled after the
                            response — background jobs would stall)
  GET  /jobs/{id}        -> status + manifest + file list
  GET  /jobs/{id}/files/{name} -> download a clip / srt / report

Auth: if env CLIPPER_TOKEN is set, POSTs to /clip and /clip-sync must
carry header "X-Clipper-Token: <token>" or they get 401.

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
# Cloud Run container disk counts against the 4 GiB memory limit, so cap
# sources at 500 MB (was 2 GB on a plain VM).
MAX_SOURCE_BYTES = 500 * 1024 * 1024  # 500 MB
CLIPPER_TOKEN = os.environ.get("CLIPPER_TOKEN", "")

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
                raise ValueError(
                    f"source larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB")
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

    def _authorized(self) -> bool:
        """Shared-secret auth for POSTs. No token configured = open (local use)."""
        if not CLIPPER_TOKEN:
            return True
        return self.headers.get("X-Clipper-Token") == CLIPPER_TOKEN

    def _parse_clip_body(self) -> tuple[dict | None, tuple[int, dict] | None]:
        """Parse + validate a /clip request body.

        Returns (params, None) on success or (None, (http_code, error_obj)).
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return None, (400, {"error": "invalid JSON"})
        url = body.get("source_url", "")
        if not urlparse(url).scheme.startswith("http"):
            return None, (400, {"error": "source_url must be a public http(s) URL"})
        clips = int(body.get("clips", 5))
        if not 1 <= clips <= MAX_CLIPS:
            return None, (400, {"error": "clips must be 1..10"})
        formats = body.get("formats", ["vertical"])
        if not formats or any(f not in ("vertical", "square", "landscape") for f in formats):
            return None, (400, {"error": "bad formats"})
        return {
            "source_url": url,
            "clips": clips,
            "formats": formats,
            "captions": bool(body.get("captions", True)),
            "language": body.get("language"),
        }, None

    def _start_job(self, params: dict) -> tuple[str, str]:
        """Create a job entry + fetch its source. Returns (job_id, src_path)."""
        job_id = _new_job_id()
        job_dir = os.path.join(OUT_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        with LOCK:
            JOBS[job_id] = {"job_id": job_id, "status": "fetching",
                            "source_url": params["source_url"]}
        url = params["source_url"]
        src_path = os.path.join(
            job_dir, "source" + os.path.splitext(urlparse(url).path)[1][:5])
        _fetch_source(url, src_path)
        return job_id, src_path

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/clip", "/clip-sync"):
            return self._json(404, {"error": "not found"})
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        params, err = self._parse_clip_body()
        if err is not None:
            code, obj = err
            return self._json(code, obj)
        try:
            job_id, src_path = self._start_job(params)
        except Exception as exc:  # noqa: BLE001
            return self._json(400, {"error": f"fetch failed: {exc}"})
        if path == "/clip-sync":
            # Synchronous: run inline so Cloud Run does not throttle the
            # CPU after the response (background jobs would stall there).
            with LOCK:
                JOBS[job_id]["status"] = "running"
            try:
                manifest = run(src_path, os.path.join(OUT_DIR, job_id),
                               clip_count=params["clips"],
                               formats=tuple(params["formats"]),
                               captions=params["captions"],
                               language=params["language"])
            except Exception as exc:  # noqa: BLE001 - surfaced in response
                with LOCK:
                    JOBS[job_id].update({"status": "error", "error": str(exc)})
                return self._json(500, {"job_id": job_id, "status": "error",
                                        "error": str(exc)})
            with LOCK:
                JOBS[job_id].update({"status": "done", "manifest": manifest})
            return self._json(200, {"job_id": job_id, "status": "done",
                                    "manifest": manifest})
        # Async (local / plain-VM use): background thread, 202 immediately.
        with LOCK:
            JOBS[job_id]["status"] = "running"
        threading.Thread(target=_worker, args=(
            job_id, src_path, params["clips"], params["formats"],
            params["captions"], params["language"],
        ), daemon=True).start()
        return self._json(202, {"job_id": job_id, "status": "running"})


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"clipper API on http://{host}:{port} (out dir: {OUT_DIR})")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8080)
