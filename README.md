# Video Clipping Agent

Long video in, platform-ready shorts out — with a stated reason for every clip.

Built for the NEAR AI Agent Market **Video Clipping Agent** job (poster Axi,
$150 USDC, pay on award): build a working agent, host it, list it on Agent
Market, submit the listing URL. The agent stays the builder's and can earn
recurring revenue.

## What it does

Send one long video. You get back:

- **Up to 10 clips** (default 5) from one source, each **18–45 seconds**,
  cut on **sentence boundaries** from a local transcript — never mid-word.
- **Formats:** vertical 9:16 (1080×1920), square 1:1 (1080×1080),
  landscape 16:9 (1920×1080). 1080p, H.264/AAC, ready to upload.
- **Burned-in captions** (on by default, large, bottom-centred) + one
  **SRT per clip**.
- A **`report.md`** per run: exact time range, spoken text, and the reason
  each moment was chosen — with the measured signals named
  (keyword density, questions, concrete numbers, audio energy,
  speech density, scene changes). No retention/virality claim is made
  when the source exposes none.

## What it does not do

- No dubbing or audio translation. No music, effects, or generated B-roll.
- No sources that need a private login — the video must be publicly
  reachable (direct media URL) or a local file.
- It does not post, schedule, or upload clips anywhere. You publish them.

## Stack — free and local only

- **ffmpeg** (system) — cutting, reframing, caption burn-in, audio/video analysis.
- **faster-whisper** (`tiny` model, int8, CPU) — local transcription with
  word-level timestamps. Model downloads once from Hugging Face (~75 MB).
- **Python stdlib** HTTP server for the API — no web framework, no paid API,
  no API keys anywhere.

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# ffmpeg must be installed on the system (apt install ffmpeg)
```

## CLI

```bash
.venv/bin/python -m clipper.cli clip tests/fixtures/sample-talk.mp4 \
    --clips 5 --formats vertical,square --out out/sample
```

Output per run: `clipN-<format>.mp4`, `clipN.srt`, `transcript.json`,
`report.md`, `manifest.json`.

## HTTP API

```bash
CLIPPER_OUT=out .venv/bin/python -m clipper.server 8080
```

- `GET /health`
- `POST /clip` — `{"source_url": "https://.../video.mp4", "clips": 5,
  "formats": ["vertical"], "captions": true, "language": "en"}` → `{"job_id": ...}`
  (async: 202, job runs in the background)
- `POST /clip-sync` — same body, runs the job inline and returns
  `{"job_id": ..., "status": "done", "manifest": ...}` when finished.
  Use this on Cloud Run (CPU is throttled after the response, so
  background jobs would stall).
- `GET /jobs/{id}` — status + manifest
- `GET /jobs/{id}/files/{name}` — download a clip / SRT / report

Auth: if env `CLIPPER_TOKEN` is set, POSTs to `/clip` and `/clip-sync`
must send header `X-Clipper-Token: <token>` (otherwise 401). The Docker
image listens on `$PORT` (default 8080). Sources are capped at 500 MB.

## How clips are chosen (transparent scoring)

1. Transcribe locally with word timestamps; group words into sentences.
2. Candidate windows = consecutive sentences, 18–45 s.
3. Score each window: 35% keyword/hook density (questions, numbers,
   hook words), 25% speech density, 20% audio energy vs the source mean,
   10% scene changes, 10% length fit (25–40 s ideal).
4. Greedy top-N, non-overlapping. The report prints every signal value.

## Test

```bash
.venv/bin/python tests/test_select.py        # unit tests (no model needed)
.venv/bin/python -m clipper.cli clip tests/fixtures/sample-talk.mp4 \
    --clips 5 --formats vertical --out out/sample   # end-to-end demo
```

The demo source (`tests/fixtures/sample-talk.mp4`, ~16.5 min) is built
from 24 public-domain speech recordings (Open Speech Repository,
voiptroubleshooter.com) over a static title slide — real English speech,
so transcription and sentence cutting are genuinely exercised.

## Hosting (see `hidden_files/near-clipping-report.md` for the full analysis)

Video processing needs ffmpeg + ~1 GB RAM, so serverless functions that
cannot run ffmpeg (e.g. Cloudflare Workers) do **not** work. The honest
free options: **Oracle Cloud free-tier Ampere VM** (24 GB RAM, always-free)
or **Hetzner/Railway/Render free tier** (RAM-limited — Render free is
512 MB, too small for whisper; Railway trial credit works short-term).
The repo is deployment-ready (systemd unit + Dockerfile notes in the
report); no deployment is included here — deploying costs $0 on Oracle
free tier but needs the account holder's own cloud account.
