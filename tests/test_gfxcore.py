"""
Unit tests for gfxcore.  Run:   python3 tests/test_gfxcore.py     (or: pytest -q)

The GL cross-check at the bottom is optional: it needs a window, so it is only run
when you pass --gl (it asks OpenGL itself for glOrtho / glFrustum matrices and
checks that ours are identical).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root, so `python3 tests/x.py` works
import math
import random
import sys

import numpy as np

import gfxcore as gx


def dist_to_segment(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def test_lines_all_slopes():
    rng = random.Random(7)
    cases = [(0, 0, 10, 0), (0, 0, 0, 10), (0, 0, 10, 10), (0, 0, 10, -10), (5, 5, -5, -5),
             (0, 0, 7, 3), (0, 0, 3, 7), (0, 0, -7, 3), (0, 0, -3, -7), (2, 9, 2, 9)]
    cases += [(rng.randint(-60, 60), rng.randint(-60, 60), rng.randint(-60, 60), rng.randint(-60, 60))
              for _ in range(500)]
    for (x0, y0, x1, y1) in cases:
        for fn in (gx.bresenham_line, gx.dda_line):
            pts = fn(x0, y0, x1, y1)
            assert pts[0] == (x0, y0) and pts[-1] == (x1, y1), (fn.__name__, x0, y0, x1, y1)
            assert len(pts) == max(abs(x1 - x0), abs(y1 - y0)) + 1
            for (px, py), (qx, qy) in zip(pts, pts[1:]):         # 8-connected, no gaps
                assert max(abs(px - qx), abs(py - qy)) == 1
            for (px, py) in pts:                                  # never farther than 1px from the ideal line
                assert dist_to_segment(px, py, x0, y0, x1, y1) <= 0.75, (fn.__name__, (x0, y0, x1, y1), (px, py))


def test_bresenham_textbook_example():
    # classic worked example: (0,0) -> (5,2)
    assert gx.bresenham_line(0, 0, 5, 2) == [(0, 0), (1, 0), (2, 1), (3, 1), (4, 2), (5, 2)]


def test_circle():
    for r in (1, 2, 5, 17, 62, 120):
        pts = gx.bresenham_circle(10, -4, r)
        for x, y in pts:
            assert abs(math.hypot(x - 10, y + 4) - r) <= 0.75, (r, x, y)
        assert (10 + r, -4) in pts and (10, -4 + r) in pts and (10 - r, -4) in pts


def liang_barsky(x0, y0, x1, y1, xmin, ymin, xmax, ymax):
    dx, dy = x1 - x0, y1 - y0
    p = [-dx, dx, -dy, dy]
    q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0]
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        else:
            t = qi / pi
            if pi < 0:
                u0 = max(u0, t)
            else:
                u1 = min(u1, t)
    if u0 > u1:
        return None
    return (x0 + u0 * dx, y0 + u0 * dy, x0 + u1 * dx, y0 + u1 * dy)


def test_cohen_sutherland_matches_reference():
    rng = random.Random(3)
    win = (-10.0, -5.0, 12.0, 9.0)
    n_in = n_out = 0
    for _ in range(4000):
        seg = [rng.uniform(-40, 40) for _ in range(4)]
        a = gx.cohen_sutherland(*seg, *win)
        b = liang_barsky(*seg, *win)
        if b is None:
            assert a is None
            n_out += 1
        else:
            assert a is not None
            assert np.allclose(a, b, atol=1e-6) or np.allclose(a, (b[2], b[3], b[0], b[1]), atol=1e-6)
            n_in += 1
    assert n_in > 300 and n_out > 300          # the test really exercises both branches


def test_outcodes():
    assert gx.outcode(0, 0, -1, -1, 1, 1) == gx.INSIDE
    assert gx.outcode(-2, 5, -1, -1, 1, 1) == gx.LEFT | gx.TOP
    assert gx.outcode(2, -5, -1, -1, 1, 1) == gx.RIGHT | gx.BOTTOM


def test_2d_composite_and_pivot():
    # rotate (3,0) by 90 degrees about (2,0) -> (2,1)
    m = gx.t2_rotate(math.pi / 2, about=(2, 0))
    assert np.allclose(gx.apply2(m, [(3, 0)]), [[2, 1]])
    # scale about a pivot leaves the pivot fixed
    m = gx.t2_scale(3, 3, about=(5, 5))
    assert np.allclose(gx.apply2(m, [(5, 5), (6, 5)]), [[5, 5], [8, 5]])
    # order matters: T then R is not R then T
    a = gx.compose(gx.t2_rotate(1.0), gx.t2_translate(4, 0))
    b = gx.compose(gx.t2_translate(4, 0), gx.t2_rotate(1.0))
    assert not np.allclose(a, b)


def test_3d_transforms():
    p = np.array([1.0, 2.0, 3.0, 1.0])
    assert np.allclose(gx.translate(1, 1, 1) @ p, [2, 3, 4, 1])
    assert np.allclose(gx.scale(2, 3, 4) @ p, [2, 6, 12, 1])
    assert np.allclose(gx.rotate_z(math.pi / 2) @ [1, 0, 0, 1], [0, 1, 0, 1])
    assert np.allclose(gx.rotate_x(math.pi / 2) @ [0, 1, 0, 1], [0, 0, 1, 1])
    assert np.allclose(gx.rotate_y(math.pi / 2) @ [0, 0, 1, 1], [1, 0, 0, 1])
    for a in (0.3, 1.1, 2.5):                        # axis form agrees with the basic ones
        assert np.allclose(gx.rotate_axis(a, (0, 0, 1)), gx.rotate_z(a))
        assert np.allclose(gx.rotate_axis(a, (1, 0, 0)), gx.rotate_x(a))
        assert np.allclose(gx.rotate_axis(a, (0, 1, 0)), gx.rotate_y(a))
    r = gx.rotate_axis(0.7, (1, 2, 3))
    assert np.allclose(r[:3, :3] @ r[:3, :3].T, np.eye(3))    # orthonormal


def test_projections():
    # perspective: near-plane centre -> z_ndc = -1, far-plane centre -> +1
    P = gx.perspective(60, 1.6, 0.5, 100)
    for z, expect in ((-0.5, -1.0), (-100.0, 1.0)):
        c = P @ [0, 0, z, 1]
        assert abs(c[2] / c[3] - expect) < 1e-9
    # a point twice as far away appears half as big (perspective foreshortening)
    a = P @ [1, 0, -10, 1]
    b = P @ [1, 0, -20, 1]
    assert abs((a[0] / a[3]) / (b[0] / b[3]) - 2.0) < 1e-9
    # orthographic: size does NOT change with depth (parallel projection)
    O = gx.ortho(-8, 8, -4.5, 4.5, 0.1, 100)
    a = O @ [1, 0, -10, 1]
    b = O @ [1, 0, -50, 1]
    assert abs(a[0] - b[0]) < 1e-12


def test_look_at():
    eye, ctr = np.array([3.0, 2.0, 5.0]), np.array([1.0, 0.0, -4.0])
    V = gx.look_at(eye, ctr, (0, 1, 0))
    assert np.allclose(V @ [*eye, 1], [0, 0, 0, 1])                       # eye -> origin
    c = V @ [*ctr, 1]
    assert abs(c[0]) < 1e-9 and abs(c[1]) < 1e-9 and c[2] < 0             # looks down -z
    assert np.allclose(V[:3, :3] @ V[:3, :3].T, np.eye(3))


def test_colour_models():
    assert gx.hsv_to_rgb(0, 1, 1) == (1, 0, 0)
    assert np.allclose(gx.hsv_to_rgb(120, 1, 1), (0, 1, 0))
    assert np.allclose(gx.hsv_to_rgb(240, 1, 1), (0, 0, 1))
    rng = random.Random(1)
    for _ in range(300):
        r, g, b = rng.random(), rng.random(), rng.random()
        assert np.allclose(gx.hsv_to_rgb(*gx.rgb_to_hsv(r, g, b)), (r, g, b), atol=1e-9)
        assert np.allclose(gx.cmy_to_rgb(*gx.rgb_to_cmy(r, g, b)), (r, g, b))
        assert np.allclose(gx.cmyk_to_rgb(*gx.rgb_to_cmyk(r, g, b)), (r, g, b), atol=1e-9)
        h, s, v = rng.uniform(0, 360), rng.random(), rng.random()
        assert np.allclose(gx.hsv_to_rgb_np(h, s, v), gx.hsv_to_rgb(h, s, v))
    assert gx.rgb_to_cmyk(0, 0, 0) == (0.0, 0.0, 0.0, 1.0)                # pure black -> K only
    assert np.allclose(gx.rgb_to_cmy(1, 0, 0), (0, 1, 1))                 # red = no cyan, full M+Y
    assert gx.hue_distance(350, 10) == 20 and gx.hue_distance(0, 180) == 180


def test_phong():
    # light, eye and normal all aligned: N.L = 1, R.V = 1 -> maximum highlight
    t = gx.phong_terms((0, 0, 0), (0, 0, 1), (0, 0, 5), (0, 0, 5), ka=0.1, kd=0.5, ks=0.5,
                       shininess=10, ambient_light=(1, 1, 1))
    assert abs(t["N.L"] - 1) < 1e-9 and abs(t["R.V"] - 1) < 1e-9
    assert np.allclose(t["specular"], 0.5) and np.allclose(t["diffuse"], 0.5)
    # light behind the surface: no diffuse and no specular, only ambient
    t = gx.phong_terms((0, 0, 0), (0, 0, 1), (0, 0, -5), (0, 0, 5), ambient_light=(1, 1, 1))
    assert t["diffuse"].sum() == 0 and t["specular"].sum() == 0
    # attenuation darkens with distance
    near = gx.phong_terms((0, 0, 0), (0, 0, 1), (0, 0, 2), (0, 0, 5), atten=(1, 0, 0.1))
    far = gx.phong_terms((0, 0, 0), (0, 0, 1), (0, 0, 9), (0, 0, 5), atten=(1, 0, 0.1))
    assert near["diffuse"].sum() > far["diffuse"].sum()
    # higher shininess -> narrower highlight
    off = dict(point=(0, 0, 0), normal=(0, 0, 1), light_pos=(3, 0, 5), eye=(-3, 0.8, 5))
    lo = gx.phong_terms(**off, shininess=5)["specular"].sum()
    hi = gx.phong_terms(**off, shininess=100)["specular"].sum()
    assert lo > hi


def test_tracks():
    lin = gx.Track([(0, (0.0, 10.0)), (2, (4.0, 20.0))], mode="linear")
    assert np.allclose(lin.at(1.0), (2.0, 15.0))
    sm = gx.Track([(0, 0.0), (1, 1.0)], mode="smooth")
    assert abs(sm.at(0.5)[0] - 0.5) < 1e-12 and sm.at(0.1)[0] < 0.1       # eases in
    cr = gx.Track([(0, 0.0), (1, 5.0), (2, -2.0), (3, 1.0)], mode="catmull")
    for t, v in ((0, 0.0), (1, 5.0), (2, -2.0), (3, 1.0)):                # interpolates its keys
        assert abs(cr.at(t)[0] - v) < 1e-9
    loop = gx.Track([(0, 0.0), (1, 5.0), (2, 1.0), (3, 0.0)], mode="catmull", loop=True)
    assert abs(loop.at(0.0)[0] - loop.at(3.0 - 1e-9)[0]) < 1e-6           # seamless wrap
    assert abs(loop.at(0.5)[0] - loop.at(3.5)[0]) < 1e-9
    assert gx.smoothstep(-1) == 0 and gx.smoothstep(2) == 1


def test_pendulum():
    p = gx.Pendulum(0.5, 2.0, 0.0)
    assert abs(p.angle(0) - 0.5) < 1e-12
    assert abs(p.angle(math.pi / 2.0) + 0.5) < 1e-9                       # half period -> opposite swing
    assert abs(gx.Pendulum(0.5, 2.0, 0.3).angle(10)) < abs(p.angle(10)) + 0.5   # damped is bounded


def test_spring():
    crit = gx.Spring(0.0, freq=4.0, damping=1.0)
    crit.target = 1.0
    peak = 0.0
    for _ in range(120):                       # 2 seconds at 60 fps
        peak = max(peak, crit.update(1 / 60))
    assert peak <= 1.0 + 1e-3 and abs(crit.x - 1.0) < 0.01 and crit.settled is False or abs(crit.x - 1.0) < 0.01
    bouncy = gx.Spring(0.0, freq=4.0, damping=0.4)
    bouncy.target = 1.0
    peak = max(bouncy.update(1 / 60) for _ in range(60))
    assert peak > 1.05                         # underdamped overshoots
    for dt in (1 / 30, 1 / 60, 1 / 144, 0.05):  # frame-rate independent end state
        s = gx.Spring(0.0, 5.0, 0.9)
        s.target = 3.0
        for _ in range(int(3.0 / dt)):
            s.update(dt)
        assert abs(s.x - 3.0) < 0.02, (dt, s.x)
    s = gx.Spring(0.0)
    s.snap(5.0)
    assert s.x == 5.0 and s.target == 5.0 and s.settled


def test_hue_names():
    assert gx.hue_name(0) == "Red" and gx.hue_name(359) == "Red" and gx.hue_name(14) == "Red"
    assert gx.hue_name(16) == "Orange" and gx.hue_name(180) == "Cyan" and gx.hue_name(240) == "Blue"
    assert gx.hue_name(300) == "Magenta" and gx.hue_name(330) == "Rose"
    assert len(set(gx.hue_name(h * 30.0) for h in range(12))) == 12      # all twelve are distinct


def gl_crosscheck():
    import os
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    from OpenGL.GL import (glMatrixMode, glLoadIdentity, glOrtho, glFrustum, glGetFloatv,
                           GL_PROJECTION, GL_PROJECTION_MATRIX)
    pygame.init()
    pygame.display.set_mode((320, 180), pygame.OPENGL | pygame.DOUBLEBUF)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glOrtho(-8, 8, -4.5, 4.5, 0.1, 100)
    ref = np.array(glGetFloatv(GL_PROJECTION_MATRIX), dtype=np.float32)
    assert np.allclose(ref, gx.gl_matrix(gx.ortho(-8, 8, -4.5, 4.5, 0.1, 100)), atol=1e-6), "ortho differs from glOrtho"
    fovy, aspect, n, f = 62.0, 16 / 9, 0.3, 400.0
    top = n * math.tan(math.radians(fovy) / 2)
    glLoadIdentity()
    glFrustum(-top * aspect, top * aspect, -top, top, n, f)
    ref = np.array(glGetFloatv(GL_PROJECTION_MATRIX), dtype=np.float32)
    assert np.allclose(ref, gx.gl_matrix(gx.perspective(fovy, aspect, n, f)), atol=1e-5), "perspective differs from glFrustum"
    print("  GL cross-check: perspective == glFrustum, ortho == glOrtho   OK")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"  ok  {name}")
    if "--gl" in sys.argv:
        gl_crosscheck()
    print(f"\nall {len(tests)} gfxcore tests passed")
