# LUMEN DRIFT - Project report

**Course:** BCS501 - Fundamentals of Computer Graphics (VTU, 5th semester, B.E. CSE)
**Student:** _your name_ &nbsp; **USN:** _your USN_ &nbsp; **Guide:** _faculty name_
**Technology:** Python 3, PyOpenGL, pygame (window / input / audio), NumPy

> Fill in the three placeholders above before submitting. Sections below are written to be edited into your own words.

## 1. Abstract

LUMEN DRIFT is a real-time 3D game in which the player is a point of light falling through an endless, bending tunnel. The player's orb is the only light source: energy is light radius, and the hue of the orb must match colour-filter gates. The game is designed so that each module of the syllabus (output primitives, transformations and viewing, colour and illumination, interaction, animation) does real work in the game rather than being a separate demo. It has two renderers - a fixed-function OpenGL pipeline and a shader-based pipeline with per-pixel Phong lighting, HDR bloom and anti-aliasing.

## 2. Objectives

1. Implement the core syllabus algorithms from first principles and use them in a working application.
2. Use OpenGL for 3D rendering, lighting, projection and depth handling.
3. Provide interactive input from keyboard, mouse and gamepad with a complete menu system.
4. Demonstrate the difference between Gouraud and Phong shading side by side.
5. Make the game robust: validated settings, automatic renderer fallback, unit and end-to-end tests.

## 3. System overview

| Part | Description |
|---|---|
| World | Infinite tunnel defined by a centre-line curve and radius function; objects placed ahead of the player |
| Entities | Pillars and spinning spoke-wheels (hazards), Spectrum Gates (hue filters), Shards (energy) |
| Rules | Energy drains over time; shards and gate matches restore it; hazards and wrong-hue gates damage; zero energy ends the run; a sonar pulse lights the way ahead at an energy cost |
| Rendering | Classic (fixed function) or Premium (GLSL 1.20 shaders, HDR, bloom, FXAA) |
| UI | Glass-style menus, HUD (score, energy, hue wheel, radar), Lab overlay with live colour and lighting values |
| Audio | Music and effects synthesised at start-up with NumPy |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module structure and frame pipeline.

## 4. Syllabus coverage

Summarised below; the full table with function names is in [SYLLABUS_MAP.md](SYLLABUS_MAP.md).

| Module | Topics implemented |
|---|---|
| 1 | DDA, Bresenham line and circle, point/line attributes, coordinate frames |
| 2 | 2D homogeneous transforms, Cohen-Sutherland clipping, 3D transforms, viewing, perspective and parallel projection, depth buffer |
| 3 | RGB / CMY / CMYK / HSV, light sources, Phong model, Gouraud vs Phong shading, fog |
| 4 | Input classification, event-driven and sampled input, menus and GUI |
| 5 | Key-frame animation (Catmull-Rom), periodic motion, double-buffered animation loop, spring-based motion |

## 5. Design decisions

- **Tunnel coordinates.** Position is `(s, u, v)` (distance along the tunnel, offset across it). World space is a closed-form function of these, so the world is infinite, memory-free and collisions are simple.
- **The light is the player.** A single `GL_LIGHT0` follows the orb; attenuation makes energy visible as light radius.
- **HSV for gameplay.** Hue is an angle, so matching a gate is an angular distance test (+/-24 degrees), and rotating the orb is one addition.
- **Pure core module.** `gfxcore.py` has no OpenGL dependency so every algorithm can be unit-tested against a reference.
- **Premium as an overlay on Classic.** Both renderers share the same scene code and the same `glLight`/`glMaterial` state; the shaders read that state, so there is one source of truth.

## 6. Implementation notes

- **Per-pixel Phong** (`shaders.LIT_FS`) reads `gl_LightSource[0]` and `gl_FrontMaterial` and adds a ribbed normal perturbation on the tunnel panels.
- **Bloom** is a bright-pass followed by four down-sample/blur levels added back, then a filmic tonemap.
- **Glass UI** draws rounded rectangles as signed-distance fields over a blurred quarter-resolution copy of the scene.
- **Gamepad** input passes through a radial dead zone so diagonals are not faster than straights; rumble feedback accompanies impacts, gates and shards.
- **Settings** are validated and range-clamped on load and written atomically.

Problems found and solved during development are listed in [PREMIUM_RENDERER.md](PREMIUM_RENDERER.md) (for example the white rectangle caused by smooth points in a float framebuffer on software OpenGL).

## 7. Testing

34 unit tests (algorithms, settings, gamepad, menu logic) and 8 end-to-end tests that drive the real game through every screen under software OpenGL, including the forced Premium-to-Classic fallback and settings persistence. See [TESTING.md](TESTING.md).

## 8. Results

Screenshots are in `docs/`: title, gameplay, settings, pause, game over, the Lab overlay, orthographic projection and a Classic-vs-Premium comparison.

## 9. Limitations

- Tested on software OpenGL only; real GPU, Apple silicon and physical controller behaviour still to be confirmed.
- Game balance values are first estimates.
- OpenGL 2.1 / GLSL 1.20 limits the techniques available (no instancing, no geometry shaders).

## 10. Future work

See [ROADMAP.md](ROADMAP.md).

## 11. References

1. Hearn, D. and Baker, M. P., *Computer Graphics with OpenGL*, Pearson (syllabus text).
2. Foley, van Dam, Feiner, Hughes, *Computer Graphics: Principles and Practice*.
3. Angel, E., *Interactive Computer Graphics: A Top-Down Approach with OpenGL*.
4. Khronos Group, *OpenGL 2.1 and GLSL 1.20 specifications*.
5. B. T. Phong, "Illumination for Computer Generated Pictures", CACM 18(6), 1975.
6. H. Gouraud, "Continuous Shading of Curved Surfaces", IEEE Trans. Computers, 1971.
7. T. Lottes, *FXAA* (NVIDIA white paper), 2009.
8. Inter typeface, Rasmus Andersson, SIL Open Font License 1.1.
