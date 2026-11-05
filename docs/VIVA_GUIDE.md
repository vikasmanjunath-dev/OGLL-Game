# Viva guide

Short answers you can say out loud, each tied to a place in the code you can open and show. Read `gfxcore.py` once end to end before the viva; it is ~500 lines and every function is a syllabus topic.

> If this is graded work: confirm with your faculty that a game is acceptable for the mini-project, follow your institution's AI-assistance policy, and make sure you can explain `gfxcore.py` and the `Game` class yourself.

## 60-second demo script

1. Launch. The title screen is live: an autopilot flies the tunnel (Module 5 camera key frames, Module 3 lighting).
2. **Play.** Point out: the orb is the light (Module 3), the hue wheel drawn with Bresenham's circle (Module 1), the radar (Module 2: transforms + Cohen-Sutherland clipping).
3. Press **Tab**: live RGB / CMY / CMYK / HSV and every Phong term (Module 3).
4. Press **V**: parallel projection, the tunnel stops converging (Module 2).
5. *Settings -> Graphics quality*: Classic <-> Premium. "Same Phong model, per vertex versus per pixel" (Module 3).
6. Mention the unit tests: `make test`.

## Module 1 - Output primitives

**DDA vs Bresenham?**
DDA: `steps = max(|dx|,|dy|)`; add float increments `dx/steps`, `dy/steps` and round. Simple, but float error accumulates and rounding costs time. Bresenham: integers only, decision parameter `p = 2dy - dx`; if `p < 0` the next pixel is `(x+1, y)` and `p += 2dy`, else `(x+1, y+1)` and `p += 2(dy - dx)`. For |slope| > 1 swap the roles of x and y. (`gfxcore.dda_line`, `bresenham_line`.)

**Midpoint / Bresenham circle?**
Compute one octant and mirror it 8 ways. `d = 3 - 2r`; if `d < 0`: `d += 4x + 6`, else `d += 4(x - y) + 10` and `y--`. (`bresenham_circle`, used for the hue wheel.)

**Point and line attributes?** Size, width, smoothing (anti-aliasing), colour per vertex: `glPointSize`, `glLineWidth`, `GL_POINT_SMOOTH`.

## Module 2 - Transformations, clipping, projection

**Why homogeneous coordinates?**
Translation is an addition, not a matrix multiply. Add a w-coordinate and it becomes one, so any sequence of transforms collapses into a single matrix. `compose(A, B, C) = A.B.C` applies **C first**.

**Rotate about an arbitrary point?** `T(p) . R . T(-p)` - `t2_rotate(theta, about=p)`.

**Cohen-Sutherland?**
Give each endpoint a 4-bit outcode (TOP, BOTTOM, RIGHT, LEFT). Both codes 0 -> trivially accept. Codes AND to non-zero -> trivially reject. Otherwise move an outside endpoint to a window edge and repeat. Used to clip the radar's tunnel walls to its window.

**Perspective vs parallel projection?**
Perspective divides by depth (`w = -z`), so distant things shrink and parallel lines converge. Orthographic does not divide, so sizes are constant. Press **V** to show both. Our `perspective` and `ortho` matrices equal `glFrustum` / `glOrtho` (proved by `test_gfxcore.py --gl`).

**Visible-surface detection?** Depth (z) buffer: per pixel keep the nearest fragment. Transparent gates are drawn last, sorted far to near, with depth writes off.

## Module 3 - Colour and lighting

**RGB vs CMY(K)?** RGB is additive (light on a screen). CMY(K) is subtractive (ink on paper): `C = 1 - R` etc.; `K = min(C, M, Y)` then subtract K from each ink. Shown live in the Tab overlay.

**Why HSV for the game?** Hue is an angle on the colour wheel, so "match the gate colour" is just *angular distance < 24 degrees*, and rotating the orb's colour is adding to one number.

**Phong illumination model?**
`I = Ia.ka + Id.kd.(N.L) + Is.ks.(R.V)^n`, with `R = 2(N.L)N - L`. Larger `n` gives a tighter highlight. Distance attenuation `1 / (kc + kl d + kq d^2)`. `gfxcore.phong_terms` returns each term separately; the Tab overlay prints them.

**Gouraud vs Phong shading? (the trap question)**
Fixed-function OpenGL evaluates the illumination model **per vertex** and interpolates colour: that is *Gouraud shading*. True *Phong shading* interpolates the **normal** and evaluates the model per pixel, which needs a fragment shader. The Premium renderer does exactly that (`shaders.LIT_FS`); the Classic renderer is Gouraud. Flip between them to show it.

**Fog?** Blends colour toward the fog colour with distance; `GL_EXP2`: `f = e^-(density.d)^2`.

## Module 4 - Interaction

**Classify the input devices.** Locator (steering / mouse position), valuator (hue wheel, scroll, sliders), choice (menu selection), pick (hit-testing menu rectangles).

**Event-driven vs sampled?** Discrete things (key press, click) arrive as events. Continuous things (held steering keys, analogue sticks) are sampled every frame. We use both. All devices map to the same action names, so one code path serves keyboard, mouse and controller.

## Module 5 - Animation

**Key-frame animation?** Specify key poses at key times; the computer generates in-betweens. `Track` supports linear, smoothstep and Catmull-Rom; Catmull-Rom passes **through** every key with continuous velocity, which is why the camera path is smooth.

**Why use `dt`?** Movement = speed x elapsed time, so the game runs at the same speed at 30 or 144 fps.

**Spring?** A damped harmonic oscillator `x'' = -k(x - target) - c x'`, integrated each frame; gives UI motion that overshoots and settles naturally.

## Questions about *your* design

- **Why is the orb the light?** It makes lighting (Module 3) the core mechanic, not decoration: energy is light radius.
- **Why a curve instead of stored geometry?** Tunnel coordinates `(s,u,v)` map to world space with one function, so the level is infinite and collisions are simple analytic tests.
- **Why two renderers?** Classic is the syllabus pipeline; Premium shows what the same ideas look like with shaders. Premium falls back automatically.
- **What did you test?** Algorithms against references and random inputs, settings against hostile files, menus and gamepad with synthetic events, and the whole game end-to-end under software OpenGL.
