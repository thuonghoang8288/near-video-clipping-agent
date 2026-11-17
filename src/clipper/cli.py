"""CLI: python -m clipper.cli clip <source> [options]

Example:
  python -m clipper.cli clip tests/fixtures/sample-talk.mp4 \
      --clips 5 --formats vertical,square --out out/sample
"""
from __future__ import annotations

import argparse
import json
import sys

from .pipeline import run


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(prog="clipper",
                                description="Long video in, platform-ready shorts out.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clip", help="clip one source video")
    c.add_argument("source", help="local video file (mp4/mov/...)")
    c.add_argument("--clips", type=int, default=5, help="clip count (default 5, max 10)")
    c.add_argument("--formats", default="vertical",
                   help="comma list: vertical,square,landscape (default vertical)")
    c.add_argument("--no-captions", action="store_true", help="skip burned-in captions")
    c.add_argument("--language", default=None, help="spoken language code, e.g. en")
    c.add_argument("--model", default="tiny", help="whisper model (default tiny)")
    c.add_argument("--out", default="out", help="output directory")
    c.add_argument("--min-secs", type=float, default=18.0)
    c.add_argument("--max-secs", type=float, default=45.0)

    args = p.parse_args(argv)
    if args.cmd == "clip":
        if not 1 <= args.clips <= 10:
            print("error: --clips must be 1..10", file=sys.stderr)
            return 2
        formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
        bad = [f for f in formats if f not in ("vertical", "square", "landscape")]
        if bad:
            print(f"error: unknown format(s): {bad}", file=sys.stderr)
            return 2
        manifest = run(
            args.source, args.out, clip_count=args.clips, formats=formats,
            captions=not args.no_captions, language=args.language,
            model=args.model, min_s=args.min_secs, max_s=args.max_secs,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
