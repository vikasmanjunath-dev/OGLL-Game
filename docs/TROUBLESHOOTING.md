# Troubleshooting

| Symptom | Fix |
|---|---|
| `zsh: command not found: python` (macOS) | Use `python3` (`python3 lumen_drift.py`). |
| `ModuleNotFoundError: No module named 'pygame'` / `OpenGL` | `python3 -m pip install -r requirements.txt` (use the same Python you run the game with). |
| `externally-managed-environment` error from pip | Use a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`, or the launcher in `scripts/`. |
| Console shows `[premium renderer unavailable - using Classic] ...` | Normal fallback. The game works; the reason is printed. Try `--quality balanced`, update the graphics driver, or report it with that line. |
| Black window / immediate crash on a laptop with two GPUs | Run with the discrete GPU, or `--quality classic`. |
| Game is slow | Settings -> Graphics quality: Balanced or Classic; turn off Bloom/Film grain; `--fps 60`; avoid Ultra on integrated graphics. |
| Tearing | Remove `--novsync`. |
| Text looks blurry on Retina | Update to the latest code (HiDPI text is rasterised at pixel scale); report your display scale if it persists. |
| No sound | Check system output; `--mute` disables audio on purpose; on Linux without ALSA the game runs silently (the `ALSA lib ...` lines are harmless). |
| Controller not detected | Plug in before or during the game (hot-plug supported); on macOS grant input permission if asked; try another cable. Menus also work with keyboard/mouse. |
| Settings misbehave after hand-editing | Delete `lumen_drift_settings.json`; it is recreated with defaults. |
| Best score is wrong or missing | Delete `lumen_drift_save.json`. |
| `Warning: regular vsync for OpenGL not available` | Harmless (software GL or driver without vsync control). |
| macOS: "OpenGL is deprecated" | Apple deprecated it but still ships OpenGL 2.1/4.1 legacy contexts; the game targets 2.1. It works on Intel and Apple silicon. |
| `pip install pygame` fails on very new Python | Use Python 3.9 to 3.13, or `pip install pygame-ce`. |

## Getting a good bug report

Run `python3 lumen_drift.py` from a terminal and copy everything it prints, plus your OS, GPU and `pip list | grep -i -E "pygame|opengl|numpy"`. Add a screenshot (F12 saves one next to the game).
