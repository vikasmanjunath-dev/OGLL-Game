# Architecture

LUMEN DRIFT is seven small Python modules plus a test suite. Everything that can be pure logic is pure logic, so it can be tested without a GPU.

```
                 +--------------------------------------------------+
                 |                 lumen_drift.py                   |
                 |   Game: loop, world, rendering, HUD, audio       |
                 +--+-----------+----------+-----------+-----------+
                    |           |          |           |
              gfxcore.py     ui.py     settings.py  gamepad.py
           (syllabus maths) (menu model) (validated   (SDL controller,
            no OpenGL        + widgets    JSON)        dead zones, rumble)
                                |
              postfx.py  <--  shaders.py
        (framebuffers, programs,   (GLSL 1.20 sources)
         bloom chain, RoundRect)
```

## Modules

| File | Responsibility | Depends on |
|---|---|---|
| `lumen_drift.py` | The game: tunnel generation, entities, `Game` class (update, render, input), `Audio` synthesis, `Text` (Inter fonts, HiDPI), HUD, command line | everything below |
| `gfxcore.py` | Syllabus algorithms and helpers: DDA, Bresenham, Cohen-Sutherland, 2D/3D transforms, projections, colour models, Phong terms, `Track` (key frames), `Pendulum`, `Spring` | NumPy only |
| `postfx.py` | `Program` (shader wrapper), `Target` (framebuffer), `PostFX` (HDR scene target, bloom chain, composite, glass backdrop), `RoundRect` (SDF panels), `PostFXError` | PyOpenGL, `shaders.py` |
| `shaders.py` | GLSL 1.20 source strings | none |
| `ui.py` | `Item` + `Menu` (pure navigation / pointer / slider logic), `draw_menu` and widget drawing | `gfxcore.Spring` |
| `settings.py` | Defaults, ranges, quality profiles, `sanitize`, `Settings` (load / atomic save) | stdlib |
| `gamepad.py` | `Gamepad` (SDL controller wrapper), `radial_deadzone`; works with synthetic events for tests | pygame |

## The world

The tunnel is a curve, not geometry stored in memory. A position along it is `s` (distance travelled); the centre line is

```
path_x(s), path_y(s)       sums of sines   -> gentle S-bends
tunnel_r(s)                radius 7.2 +/- ~1.4
world_pos(s, u, v) = (path_x(s) + u, path_y(s) + v, -s)     forward is -z
```

The player lives in `(s, u, v)`: `s` advances automatically (`base_speed()` ramps 24 -> 58 units/s over ~100 s), while `u, v` are steered inside the tunnel radius. Rings are drawn every `RING_DS = 2.5` units, `NR = 96` rings ahead, `NSEG = 40` segments each; index buffers are built once (`_build_tunnel_indices`).

Entities (`Pillar`, `Wheel`, `Gate`, `Shard`) are generated ahead of the player by `spawn_piece` and discarded behind; each has a cheap analytic `hit` test in tunnel coordinates, so no physics engine is needed.

## One frame

```
Game.run()                                  60 fps target, dt-based
  handle(events)  ->  do_action(...)        keyboard / mouse / gamepad all become the same action names
  step(dt, keys)  ->  menus, steering, world update, interactions(), audio beat
  render()
    Classic:  scene -> HUD
    Premium:  fx.begin_scene()              bind HDR target
              draw_tunnel / draw_solids      per-pixel Phong (LIT shader) or fixed-function
              draw_glow / draw_membranes     additive emissive geometry (GLOW shader)
              fx.make_backdrop()             1/4-res blurred copy, used by glass panels
              fx.finish(...)                 bloom, tonemap, FXAA, aberration, grain -> screen
              HUD + glass UI                 2D, drawn in a 720-unit logical frame
```

## Unified input

All three input devices produce the same action strings: `up down left right confirm back prev next pause pulse`. `Game.do_action` is the only place that reacts to them, which is why a test can drive the whole game with `g.do_action("confirm")`. Continuous steering is sampled separately (keys held, analogue stick) in `step`.

## Failure handling

| Failure | What happens |
|---|---|
| Shader fails to compile, FBO incomplete, no float textures | `PostFXError` -> console message -> Classic renderer |
| RGBA16F unsupported | falls back to an 8-bit buffer, Premium keeps running |
| Controller unplugged during play | game pauses |
| Settings file corrupt or hand-edited | each value is sanitised; bad ones revert to defaults |
| Save file unwritable | ignored (the best score just isn't kept) |

## Files the game writes

`lumen_drift_save.json` (best score) and `lumen_drift_settings.json`, both next to `lumen_drift.py`, both git-ignored.
