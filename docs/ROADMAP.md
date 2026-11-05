# Roadmap

Ideas that are **not built yet**, roughly in priority order.

## Gameplay
- Modes: Daily Run (seeded), Time Attack, Zen (no hazards)
- Power-ups (shield, magnet, slow-time); short guided tutorial
- Local leaderboard and ghost replay of the best run
- Adaptive music that follows energy and chain

## Polish
- Orb skins and tunnel themes (unlockable)
- Key remapping and controller button remapping
- Photo mode / replay export

## Platform
- Packaged downloads: macOS `.app`, Windows `.exe` (PyInstaller)
- Optional OpenGL 3.3 core path with instancing for denser worlds
- Validate on real GPUs (Apple silicon, NVIDIA, AMD, Intel) and several controllers

## Engineering
- Golden-image comparison in CI for the screenshot scenes
- Profiling overlay (CPU / GPU time per pass)
- Type hints across `lumen_drift.py` and a lint step in CI
