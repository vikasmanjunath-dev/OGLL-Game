# Premium renderer

The Premium pipeline adds modern-look rendering on top of the same scene code, using only features of **OpenGL 2.1 + GLSL 1.20** so it runs on macOS's legacy context as well as Windows and Linux. The shader sources are in `shaders.py`; the plumbing is in `postfx.py`.

## Pipeline

```
 scene  --(LIT / GLOW shaders)-->  HDR target (RGBA16F, depth)           full resolution x render scale
                                        |
                                bright-pass (threshold)
                                        |
                       down-sample x4  ->  blur (separable)  ->  up-sample + add
                                        |
 COMPOSITE: scene + bloom -> exposure -> filmic tonemap -> FXAA
            + chromatic aberration + radial blur (speed / impact) + grain + vignette
                                        |
                                    screen
 backdrop: 1/4-res blurred copy of the scene  -> sampled by glass panels (frosted-glass UI)
```

## Shaders

| Constant | Stage | Purpose |
|---|---|---|
| `LIT_VS` / `LIT_FS` | scene | Per-pixel Phong: reads `gl_LightSource[0]` and `gl_FrontMaterial`, so the same `glLight*` / `glMaterial*` calls feed both renderers. Optional ribbed normal bump on tunnel panels, rim light, exponential fog |
| `GLOW_VS` / `GLOW_FS` | scene | Emissive additive geometry (grid, sprites, particles, trails) with an HDR gain and distance fog |
| `QUAD_VS` | post | Full-screen triangle pair |
| `BRIGHT_FS`, `DOWN_FS`, `BLUR_FS` | post | Bloom chain |
| `COMPOSITE_FS` | post | Tone mapping, anti-aliasing and screen effects |
| `ROUNDRECT_VS` / `ROUNDRECT_FS` | UI | Signed-distance rounded rectangle with border, soft shadow and optional frosted-glass backdrop |

## Why per-pixel Phong matters for the syllabus

Fixed-function OpenGL evaluates the Phong illumination model **at the vertices** and interpolates the colour (Gouraud shading). A specular highlight that falls in the middle of a large polygon is lost. The Premium shader evaluates the same equation **per fragment** from interpolated normals (true Phong shading). Switch *Settings -> Graphics quality* between Classic and Premium while looking at the tunnel panels to see the difference. The Lab overlay (Tab) shows which one is active.

## Quality presets

| Preset | Pipeline | Render scale | Bloom levels |
|---|---|---|---|
| Classic | fixed function, 4x MSAA | 1.0 | - |
| Balanced | Premium | 0.85 | 3 |
| Premium | Premium | 1.0 | 4 |
| Ultra | Premium | 1.5 (supersampled) | 4 |

## Lessons baked into the code

- **Samplers vs floats**: `Program.seti` sets sampler (int) uniforms, `Program.set` always sends floats. Mixing them raised `GL_INVALID_OPERATION` on some drivers.
- **Never draw smooth `GL_POINTS` into a float target.** On Mesa's software rasteriser the falloff produced `inf`, which bloom spread across the whole screen as a white rectangle. Premium draws particles as soft camera-facing quads through the glow shader instead (`Game.draw_points`).
- **Shadows must fade to zero before the quad's edge**, otherwise a faint rectangle shows around glass panels (smoothstep to 0 at the padding boundary).
- **HiDPI**: the GL viewport uses the drawable size while the window uses logical size; text is rasterised at `pixel-scale x size` so it stays crisp on Retina.

## Debugging a driver problem

1. Run `python3 lumen_drift.py --quality classic`; if that works, the issue is in the Premium path.
2. Read the console: a failure prints `[premium renderer unavailable - using Classic] <reason>`.
3. Try `--quality balanced` (smaller buffers).
4. Open an issue with the console output, OS and GPU.
