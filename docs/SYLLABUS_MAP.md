# Syllabus map - BCS501 Fundamentals of Computer Graphics

Every syllabus topic is implemented **and used by the game**. Code written from scratch lives in `gfxcore.py` (pure Python + NumPy, no OpenGL import, unit-tested in `tests/test_gfxcore.py`).

## Module 1 - Output primitives

| Topic | Implementation | Used for |
|---|---|---|
| DDA line | `gfxcore.dda_line` | HUD bar ticks, hue-wheel needle, gate tolerance arc |
| Bresenham line | `gfxcore.bresenham_line` (all slopes and directions) | HUD frames, radar lines |
| Bresenham circle | `gfxcore.bresenham_circle` (8-way symmetry) | the hue wheel; each pixel coloured by its angle |
| Point and line attributes | `glPointSize`, `glLineWidth`, `GL_POINT_SMOOTH`, `GL_LINE_SMOOTH`, per-vertex colour | HUD and particles |
| Coordinate reference frames | tunnel `(s,u,v)` -> world (`world_pos`); logical 720-unit HUD frame via `glOrtho` | everywhere |

## Module 2 - Transformations, clipping, viewing

| Topic | Implementation | Used for |
|---|---|---|
| 2D homogeneous transforms, composite, pivot rotation | `t2_translate/rotate/scale`, `compose`, `apply2` | radar maps world -> screen with `T . S` |
| Cohen-Sutherland line clipping | `gfxcore.outcode`, `cohen_sutherland` | radar walls clipped to the radar window |
| 3D translate / rotate / scale, composite | `translate`, `rotate_x/y/z`, `rotate_axis`, `scale`; `glTranslatef . glRotatef . glScalef` | places every pillar and spoke |
| Viewing | `look_at` (= `gluLookAt`) | chase / close / cockpit cameras |
| Perspective and parallel projection | `perspective`, `ortho` loaded with `glLoadMatrixf` | press **V** to switch; tested equal to `glFrustum` / `glOrtho` |
| Visible-surface detection | depth buffer; transparent gates sorted far->near with depth writes off | correct occlusion |

## Module 3 - Colour and illumination

| Topic | Implementation | Used for |
|---|---|---|
| RGB, CMY, CMYK, HSV | `rgb_to_cmy/cmyk`, `hsv_to_rgb`, `rgb_to_hsv`, `hue_distance` | gameplay hue; live values in the Lab overlay (Tab) |
| Light sources, ambient / diffuse / specular | `glLightfv`, `glMaterialfv`, `GL_LIGHT0` at the orb, quadratic attenuation | the orb lights the world |
| Phong illumination model | `gfxcore.phong_terms` (Lab overlay shows each term) | explanation + verification |
| Gouraud vs Phong shading | Classic = per-vertex; Premium = per-pixel (`shaders.LIT_FS`) | switch quality to compare |
| Atmospheric depth | `GL_FOG` with `GL_EXP2` (fog term in the shaders for Premium) | depth cue |

## Module 4 - Interactive input and GUI

| Topic | Implementation |
|---|---|
| Input classification (locator, valuator, choice, pick) | steering = locator, hue wheel / scroll = valuator, menus = choice, hit-tested rectangles = pick |
| Event-driven vs sampled input | `KEYDOWN`, `MOUSEMOTION`, `MOUSEBUTTONDOWN`, controller buttons (events); `get_pressed`, analogue sticks (sampled) |
| Menus and GUI | `ui.Menu` (keyboard, mouse hover/click/drag, gamepad), `ui.draw_menu` |

## Module 5 - Animation

| Topic | Implementation |
|---|---|
| Key-frame animation, in-betweening | `gfxcore.Track` - linear, smoothstep, Catmull-Rom, loopable -> title fly-through, game-over pull-back |
| Periodic motion | rotating wheels `theta = theta0 + omega t`, bobbing shards, `Pendulum`, beat-synced grid pulse |
| Animation procedures | double-buffered loop; `dt`-based update (frame-rate independent) |
| Physically-based motion | `gfxcore.Spring` (damped harmonic oscillator) for every UI animation |

## Where each algorithm is tested

| Test file | What it proves |
|---|---|
| `tests/test_gfxcore.py` | Bresenham/DDA against random lines, circle symmetry, Cohen-Sutherland vs Liang-Barsky, matrix identities, projection matrices equal OpenGL's (`--gl`), colour round trips, Phong edge cases, Catmull-Rom passes through its keys |
