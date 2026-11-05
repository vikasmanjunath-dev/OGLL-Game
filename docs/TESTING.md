# Testing

## Run everything

```bash
make test       # 34 unit tests, no GPU / window required   (~2 s)
make smoke      # 8 end-to-end tests of the real game       (needs OpenGL)
```

Without `make`:

```bash
SDL_VIDEODRIVER=dummy python3 -m pytest tests -q --ignore=tests/test_smoke.py
python3 tests/test_smoke.py                  # desktop
xvfb-run -a python3 tests/test_smoke.py      # headless Linux (installs: xvfb libgl1-mesa-dri)
```

The smoke test is skipped by pytest on Linux without a display (set `LUMEN_SMOKE=1` to force it).

## What each file covers

| File | Tests | Covers |
|---|---|---|
| `tests/test_gfxcore.py` | 15 | DDA and Bresenham on random lines and all slopes, circle, outcodes, Cohen-Sutherland vs a Liang-Barsky reference, 2D/3D transform composition and pivot rotation, perspective/ortho/look-at (add `--gl` to compare against OpenGL's own matrices), colour models, Phong terms, key-frame tracks, pendulum, spring, hue names |
| `tests/test_settings.py` | 6 | defaults valid, round trip, clamping and type coercion, corrupt / hostile files, atomic save leaves no temp files, reset |
| `tests/test_gamepad.py` | 7 | button to action mapping, dead zone and steering, D-pad, hue rate, menu repeat, disconnect resets state, rumble without hardware |
| `tests/test_ui.py` | 6 | navigation skips gaps/disabled rows, value changes, buttons, tabs, pointer hit-testing and dragging, spring animation |
| `tests/test_smoke.py` | 8 | boots Premium and renders; title -> settings -> quality switch; every settings tab; full run -> pause -> game over -> retry -> menu; gamepad drives menus and game; colour-blind labels; fallback when the Premium pipeline is forced to fail; settings persist between runs |

## Manual checklist before a release

- [ ] Premium and Classic both start; switching at run time works
- [ ] Title, Settings (3 tabs), Controls, Pause, Game Over screens look right at 1280x720 and in fullscreen
- [ ] Keyboard-only, mouse-only (menus) and controller-only play-throughs
- [ ] Unplugging the controller pauses the game
- [ ] Colour-blind labels on: gates named, HUD names hue
- [ ] Reduced motion off: no shake, aberration, speed lines
- [ ] `lumen_drift_save.json` / `lumen_drift_settings.json` not committed (`git status`)

## Known verification gaps

Verified on software OpenGL (Mesa llvmpipe) under Xvfb. **Not yet verified on:** a real GPU or Apple silicon, a physical controller (synthetic events only), and the audio mix by ear. Gameplay balance values (`base_speed`, `spawn_piece`, `HUE_TOL`) are first guesses.

## Regenerating screenshots

`make shots` replays a scripted session and rewrites the images in `docs/`.
