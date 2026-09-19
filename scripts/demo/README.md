# Product demo recorder

Records the cockpit walkthrough used for the project's demo video: a
captioned, cursor-visible tour of the real UI over a seeded workspace, with
title and end cards. Nothing here is mocked — the daemon, the run engine and
the exported guide are the real thing.

```bash
# from the repository root, with web/dist built and web/node_modules installed
python3 scripts/demo/seed.py /tmp/ep-demo-ws          # finished + mid-run + new courses
node scripts/demo/demo.mjs /tmp/ep-demo-ws /tmp/demo   # writes /tmp/demo/*.webm
ffmpeg -i /tmp/demo/*.webm -c:v libx264 -crf 19 -pix_fmt yuv420p \
  -movflags +faststart -r 30 -an demo.mp4
```

- `seed.py` drives the shipped `examples/feedback-loops` sources through a
  full run (via `scripts/build_example.py`), adds one course waiting for
  review and one with no run yet.
- `demo.mjs` boots a daemon over that workspace, records 1920×1080 at 25 fps
  through Playwright, and injects a caption bar, a cursor and scene fades on
  every page (`bypassCSP` so the exported guide's strict policy does not
  block the overlay). Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to reuse a
  pre-installed browser.
- `title.html`, `end.html`, `card.css` are the bookend cards.

The recording is deterministic apart from timestamps; re-run it after a
visual change to refresh the video.
