# Changelog

All notable changes to LUMEN DRIFT. Format follows [Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [2.0.0] - 2026-11-06

### Added
- **Premium renderer** (GLSL 1.20, compatible with macOS's OpenGL 2.1 legacy context): per-pixel Phong lighting with a ribbed normal bump on the tunnel, HDR (RGBA16F) scene buffer, 4-level bloom, filmic tonemap, FXAA, chromatic aberration and radial blur driven by speed/impacts, film grain, vignette.
- **Automatic fallback** to the Classic fixed-function pipeline if framebuffers, shaders or float textures are unavailable.
- **Quality presets**: Classic, Balanced (85 % render scale), Premium, Ultra (150 % render scale). Switchable at run time.
- **Glass UI**: signed-distance-field rounded panels frosted by a blurred copy of the 3D scene; spring-animated hover/switch/slider; full title, settings, controls, pause and game-over screens.
- **Settings** (graphics / audio / gameplay) saved to `lumen_drift_settings.json`: validated, range-clamped, atomically written.
- **Accessibility**: colour-blind labels (gates named in the world, hue named in the HUD, lettered hue wheel), reduced-motion option.
- **Gamepad** support through SDL: radial dead zone, hot-plug, rumble, menu navigation, pause on unplug.
- Bundled **Inter** fonts (SIL OFL) for crisp HiDPI text.
- Developer flags: `--quality`, `--settings`, `--no-save`, `--classic`.
- **Repository**: tests moved to `tests/` with a pytest config, Makefile, CI workflow (unit tests on Python 3.9/3.11/3.12 and a software-OpenGL smoke test), launcher scripts, screenshot generator, and a full documentation set in `docs/`.

### Fixed
- Smooth `GL_POINTS` rendered into a float framebuffer produced `inf` on software GL and a white screen rectangle; Premium now draws dots as soft quads.
- Float/int uniform type mismatch (`glUniform1i` on a float uniform) caused a GL error on some drivers.
- Several UI layout issues (overlapping labels on the title, tall settings panel, controls panel height).

## [1.0.0] - 2026-11-05

### Added
- First release: the endless-tunnel game where the player is the light, with hue-matching gates, hazards, sonar pulse, generated audio and the Lab overlay.
- `gfxcore.py`: DDA, Bresenham line and circle, Cohen-Sutherland, 2D/3D homogeneous transforms, perspective/orthographic/look-at matrices, RGB/CMY/CMYK/HSV conversions, Phong terms, Catmull-Rom key-frame tracks, pendulum.
