# Demo fixtures (not committed — 56 MB of binary audio/video)

The end-to-end demo (`clip tests/fixtures/sample-talk.mp4 --clips 5 --formats vertical`)
needs a ~16.5 min source video built from 24 public-domain English speech
recordings (Open Speech Repository, voiptroubleshooter.com) over a static
title slide. The unit tests (`tests/test_select.py`) need no fixtures.

## Regenerate the demo source

1. Download the 24 OSR 8kHz wav files into `tests/fixtures/osr/`:
   `OSR_us_000_0010_8k.wav`, `0011`, `0012`, `0013`, `0014`, `0015`,
   `0016`, `0017`, `0018`, `0019`, `0030`, `0031`, `0032`, `0034`,
   `0035`, `0036`, `0037`, `0038`, `0039`, `0040`, `0057`, `0059`,
   `0060`, `0061` — plus a 0.5s silence clip `silence-0.5s.wav`
   (generate with `ffmpeg -f lavfi -i anullsrc=r=8000:cl=mono -t 0.5`).
   Source: https://www.voiptroubleshooter.com/open_speech/american.html
2. Build the concat list (speech file, silence, speech file, silence, ...):
   `for f in tests/fixtures/osr/OSR_us_*.wav; do echo "file '$PWD/$f'"; echo "file '$PWD/tests/fixtures/osr/silence-0.5s.wav'"; done > /tmp/concat.txt`
3. Concatenate the audio, then mux it over a static title slide:
   `ffmpeg -f concat -safe 0 -i /tmp/concat.txt -c:a aac -b:a 128k /tmp/talk.m4a`
   `ffmpeg -loop 1 -i <title-slide.png> -i /tmp/talk.m4a -c:v libx264 -t <duration> -c:a copy tests/fixtures/sample-talk.mp4`
