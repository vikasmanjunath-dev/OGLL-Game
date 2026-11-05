# Contributing

Thanks for helping with LUMEN DRIFT. It is a small codebase on purpose; this page tells you how to work in it.

## Set up

```bash
git clone <your fork>
cd lumen-drift
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
make run                                                  # or: python3 lumen_drift.py
```

## Before you open a pull request

```bash
make test      # 34 unit tests, no GPU or window needed
make smoke     # drives the real game through every screen; needs OpenGL (on headless Linux: xvfb-run -a ...)
```

Also launch the game once with `--quality classic` **and** the default Premium. Every visual change must work in both.

## Ground rules

- **`gfxcore.py` stays free of OpenGL and pygame.** It is the syllabus code: pure Python + NumPy, unit-tested. If you add an algorithm there, add a test next to the others in `tests/test_gfxcore.py`.
- **Menus are logic first.** Navigation and value changes live in `ui.Menu` and are tested without a window. Drawing is a separate function.
- **Settings go through `settings.py`.** Add a default, a range (if numeric) and a UI row; `sanitize` keeps a bad file from breaking the game.
- **Premium must degrade.** Anything that can fail on a driver (shader compile, float textures, framebuffers) raises `postfx.PostFXError` so the game falls back to Classic instead of crashing.
- **Target OpenGL 2.1 / GLSL 1.20.** That is the ceiling on macOS.
- No new heavy dependencies. Audio is synthesised at start-up, there are no audio files.
- Python 3.9+ syntax (`from __future__ import annotations` is used for type hints).

## Style

4-space indentation, LF line endings, ~120 columns (see `.editorconfig`). Comments explain *why* (and for syllabus code, which topic it implements). No formatter is enforced.

## Commits and PRs

- Small commits, imperative subject line (`Fix FXAA edge on HiDPI`, not `fixed stuff`).
- Describe how you tested. Attach a screenshot (F12 in game) for visual changes.
- Update `CHANGELOG.md` for anything a player or a grader would notice.

## Regenerating screenshots

```bash
make shots      # needs pillow; on headless Linux:  xvfb-run -a python3 scripts/make_screenshots.py
```

## Reporting bugs

Use the issue template. The most useful details are your OS/GPU and any `[premium renderer unavailable ...]` line from the console.
