"""
gfxcore.py  -  the BCS501 syllabus algorithms, written from scratch.

No OpenGL is imported here on purpose: everything in this file is plain
Python + NumPy, so each algorithm can be unit-tested, printed, and explained
in a viva without a window.  The game (lumen_drift.py) imports these and
uses them for real work (HUD drawing, clipping, projection, colour, light,
keyframe animation) - they are not decoration.

Syllabus map
------------
Module 1  dda_line, bresenham_line, bresenham_circle
Module 2  2D homogeneous transforms (t2_*), cohen_sutherland,
          3D transforms (translate/scale/rotate_*), perspective, ortho, look_at
Module 3  RGB / CMY / CMYK / HSV conversions, phong_terms (ambient+diffuse+specular)
Module 5  Track (key-frame animation: linear, smoothstep, Catmull-Rom), Pendulum
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[int, int]


# =====================================================================
# MODULE 1 - line and circle generation
# =====================================================================
def dda_line(x0: float, y0: float, x1: float, y1: float) -> List[Point]:
    """Digital Differential Analyser.

    steps = max(|dx|,|dy|); increment = (dx/steps, dy/steps); add and round.
    Uses floating point, so it is simple but accumulates rounding error.
    """
    dx, dy = x1 - x0, y1 - y0
    steps = int(max(abs(dx), abs(dy)))
    if steps == 0:
        return [(int(math.floor(x0 + 0.5)), int(math.floor(y0 + 0.5)))]
    xi, yi = dx / steps, dy / steps
    x, y = float(x0), float(y0)
    pts: List[Point] = []
    for _ in range(steps + 1):
        pts.append((int(math.floor(x + 0.5)), int(math.floor(y + 0.5))))
        x += xi
        y += yi
    return pts


def bresenham_line(x0: int, y0: int, x1: int, y1: int) -> List[Point]:
    """Bresenham's line algorithm for ALL slopes (all eight octants).

    Integer only.  The decision parameter p tells us whether the next pixel is
    (x+1, y) or (x+1, y+1).  When |slope| > 1 the roles of x and y swap
    ("steep" branch).  Direction signs sx, sy handle negative slopes.
    """
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    pts: List[Point] = []
    x, y = x0, y0
    if dx >= dy:                       # shallow: step in x, decide y
        p = 2 * dy - dx
        for _ in range(dx + 1):
            pts.append((x, y))
            x += sx
            if p >= 0:
                y += sy
                p += 2 * (dy - dx)
            else:
                p += 2 * dy
    else:                              # steep: step in y, decide x
        p = 2 * dx - dy
        for _ in range(dy + 1):
            pts.append((x, y))
            y += sy
            if p >= 0:
                x += sx
                p += 2 * (dx - dy)
            else:
                p += 2 * dx
    return pts


def bresenham_circle(xc: int, yc: int, r: int) -> List[Point]:
    """Bresenham / mid-point circle: compute one octant, mirror it 8 ways.

    d0 = 3 - 2r ;  if d<0: d += 4x+6  else: d += 4(x-y)+10, y -= 1
    """
    pts = set()
    x, y, d = 0, int(r), 3 - 2 * int(r)
    while x <= y:
        for a, b in ((x, y), (y, x)):
            for sx in (1, -1):
                for sy in (1, -1):
                    pts.add((xc + sx * a, yc + sy * b))
        if d < 0:
            d += 4 * x + 6
        else:
            d += 4 * (x - y) + 10
            y -= 1
        x += 1
    return sorted(pts)


# =====================================================================
# MODULE 2 - 2D geometric transformations (homogeneous 3x3)
# =====================================================================
def t2_translate(tx: float, ty: float) -> np.ndarray:
    return np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], dtype=np.float64)


def t2_rotate(theta: float, about: Tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    """Rotation by theta radians about a pivot: T(p) . R . T(-p)  (composite)."""
    c, s = math.cos(theta), math.sin(theta)
    r = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)
    px, py = about
    return t2_translate(px, py) @ r @ t2_translate(-px, -py)


def t2_scale(sx: float, sy: float, about: Tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    s = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=np.float64)
    px, py = about
    return t2_translate(px, py) @ s @ t2_translate(-px, -py)


def compose(*mats: np.ndarray) -> np.ndarray:
    """compose(A, B, C) == A @ B @ C  -> C is applied to the point FIRST."""
    out = np.eye(mats[0].shape[0])
    for m in mats:
        out = out @ m
    return out


def apply2(m: np.ndarray, pts: Iterable[Tuple[float, float]]) -> np.ndarray:
    a = np.asarray(list(pts), dtype=np.float64).reshape(-1, 2)
    h = np.hstack([a, np.ones((len(a), 1))])
    return (h @ m.T)[:, :2]


# ---- Cohen-Sutherland line clipping ---------------------------------
INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8


def outcode(x: float, y: float, xmin: float, ymin: float, xmax: float, ymax: float) -> int:
    code = INSIDE
    if x < xmin:
        code |= LEFT
    elif x > xmax:
        code |= RIGHT
    if y < ymin:
        code |= BOTTOM
    elif y > ymax:
        code |= TOP
    return code


def cohen_sutherland(x0: float, y0: float, x1: float, y1: float,
                     xmin: float, ymin: float, xmax: float, ymax: float
                     ) -> Optional[Tuple[float, float, float, float]]:
    """Clip a segment to a rectangle.  Returns None if fully outside.

    trivial accept : both outcodes 0
    trivial reject : outcode0 AND outcode1 != 0
    otherwise      : move an outside end-point onto the window edge it crosses
                     (order TOP, BOTTOM, RIGHT, LEFT) and repeat.
    """
    c0 = outcode(x0, y0, xmin, ymin, xmax, ymax)
    c1 = outcode(x1, y1, xmin, ymin, xmax, ymax)
    while True:
        if not (c0 | c1):
            return (x0, y0, x1, y1)
        if c0 & c1:
            return None
        c = c0 if c0 else c1
        if c & TOP:
            x = x0 + (x1 - x0) * (ymax - y0) / (y1 - y0)
            y = ymax
        elif c & BOTTOM:
            x = x0 + (x1 - x0) * (ymin - y0) / (y1 - y0)
            y = ymin
        elif c & RIGHT:
            y = y0 + (y1 - y0) * (xmax - x0) / (x1 - x0)
            x = xmax
        else:  # LEFT
            y = y0 + (y1 - y0) * (xmin - x0) / (x1 - x0)
            x = xmin
        if c == c0:
            x0, y0 = x, y
            c0 = outcode(x0, y0, xmin, ymin, xmax, ymax)
        else:
            x1, y1 = x, y
            c1 = outcode(x1, y1, xmin, ymin, xmax, ymax)


# =====================================================================
# MODULE 2 - 3D geometric transformations (homogeneous 4x4, column vectors)
# =====================================================================
def translate(tx: float, ty: float, tz: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (tx, ty, tz)
    return m


def scale(sx: float, sy: float, sz: float) -> np.ndarray:
    return np.diag([sx, sy, sz, 1.0])


def rotate_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def rotate_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def rotate_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def rotate_axis(a: float, axis: Sequence[float]) -> np.ndarray:
    """Rodrigues rotation about an arbitrary axis through the origin."""
    x, y, z = np.asarray(axis, dtype=np.float64) / np.linalg.norm(axis)
    c, s = math.cos(a), math.sin(a)
    t = 1 - c
    m = np.eye(4)
    m[:3, :3] = [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
                 [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
                 [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]
    return m


def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    """Perspective projection (same matrix as gluPerspective)."""
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2.0 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def ortho(l: float, r: float, b: float, t: float, n: float, f: float) -> np.ndarray:
    """Parallel (orthographic) projection (same matrix as glOrtho)."""
    m = np.eye(4)
    m[0, 0] = 2.0 / (r - l)
    m[1, 1] = 2.0 / (t - b)
    m[2, 2] = -2.0 / (f - n)
    m[0, 3] = -(r + l) / (r - l)
    m[1, 3] = -(t + b) / (t - b)
    m[2, 3] = -(f + n) / (f - n)
    return m


def look_at(eye: Sequence[float], center: Sequence[float], up: Sequence[float]) -> np.ndarray:
    """View matrix (same as gluLookAt): camera frame (right, up, -forward)."""
    eye = np.asarray(eye, dtype=np.float64)
    f = np.asarray(center, dtype=np.float64) - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def gl_matrix(m: np.ndarray) -> np.ndarray:
    """Math matrix -> the float32 column-major layout glLoadMatrixf expects."""
    return np.ascontiguousarray(m.T, dtype=np.float32)


# =====================================================================
# MODULE 3 - colour models
# =====================================================================
def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[float, float, float]:
    """h in degrees [0,360), s,v in [0,1]  ->  r,g,b in [0,1]."""
    h = (h % 360.0) / 60.0
    i = int(h) % 6
    f = h - math.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]


def rgb_to_hsv(r: float, g: float, b: float) -> Tuple[float, float, float]:
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == r:
        h = 60.0 * (((g - b) / d) % 6)
    elif mx == g:
        h = 60.0 * ((b - r) / d + 2)
    else:
        h = 60.0 * ((r - g) / d + 4)
    s = 0.0 if mx == 0 else d / mx
    return h % 360.0, s, mx


def hsv_to_rgb_np(h, s, v) -> np.ndarray:
    """Vectorised hsv_to_rgb; inputs broadcast, output shape (..., 3)."""
    h, s, v = np.broadcast_arrays(np.asarray(h, float), np.asarray(s, float), np.asarray(v, float))
    hh = (h % 360.0) / 60.0
    i = np.floor(hh).astype(int) % 6
    f = hh - np.floor(hh)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def rgb_to_cmy(r: float, g: float, b: float) -> Tuple[float, float, float]:
    return 1 - r, 1 - g, 1 - b


def cmy_to_rgb(c: float, m: float, y: float) -> Tuple[float, float, float]:
    return 1 - c, 1 - m, 1 - y


def rgb_to_cmyk(r: float, g: float, b: float) -> Tuple[float, float, float, float]:
    """K = min(C,M,Y); remove it from the three inks (under-colour removal)."""
    c, m, y = rgb_to_cmy(r, g, b)
    k = min(c, m, y)
    if k >= 1.0:
        return 0.0, 0.0, 0.0, 1.0
    return (c - k) / (1 - k), (m - k) / (1 - k), (y - k) / (1 - k), k


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> Tuple[float, float, float]:
    return (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues, in degrees [0,180]."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


# =====================================================================
# MODULE 3 - illumination: ambient + diffuse + specular (Phong)
# =====================================================================
def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def phong_terms(point, normal, light_pos, eye,
                ka=0.1, kd=0.7, ks=0.6, shininess=40.0,
                ambient_light=(0.1, 0.1, 0.1),
                light_diffuse=(1.0, 1.0, 1.0), light_specular=(1.0, 1.0, 1.0),
                atten=(1.0, 0.0, 0.0)) -> dict:
    """I = Ia*ka  +  Id*kd*(N.L)/att  +  Is*ks*(R.V)^n/att

    R = 2(N.L)N - L is the mirror direction of L about N.
    atten = (constant, linear, quadratic) exactly like GL_*_ATTENUATION.
    """
    p = np.asarray(point, float)
    n = _unit(np.asarray(normal, float))
    to_light = np.asarray(light_pos, float) - p
    d = float(np.linalg.norm(to_light))
    l = to_light / d if d > 0 else np.array([0, 0, 1.0])
    v = _unit(np.asarray(eye, float) - p)
    ndl = max(0.0, float(n @ l))
    r = 2.0 * (n @ l) * n - l
    rdv = max(0.0, float(r @ v)) if ndl > 0 else 0.0
    att = 1.0 / (atten[0] + atten[1] * d + atten[2] * d * d)
    amb = ka * np.asarray(ambient_light, float)
    dif = kd * ndl * att * np.asarray(light_diffuse, float)
    spe = ks * (rdv ** shininess) * att * np.asarray(light_specular, float)
    return {"ambient": amb, "diffuse": dif, "specular": spe,
            "total": np.clip(amb + dif + spe, 0.0, 1.0), "N.L": ndl, "R.V": rdv, "att": att}


# =====================================================================
# MODULE 5 - animation: key frames and periodic motion
# =====================================================================
def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def smoothstep(t: float) -> float:
    t = clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def ease_out_back(t: float) -> float:
    t = clamp01(t)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


class Track:
    """Key-frame track: a list of (time, value) with interpolation between.

    mode = 'linear' | 'smooth' (smoothstep ease) | 'catmull' (Catmull-Rom spline,
    passes through every key with continuous velocity - ideal for camera paths).
    loop=True wraps time and the spline so the motion is seamless.
    """

    def __init__(self, keys: Sequence[Tuple[float, Sequence[float]]], mode: str = "catmull",
                 loop: bool = False):
        self.t = np.array([k[0] for k in keys], dtype=np.float64)
        self.v = np.array([k[1] for k in keys], dtype=np.float64)
        if self.v.ndim == 1:
            self.v = self.v[:, None]
        self.mode, self.loop = mode, loop
        self.duration = float(self.t[-1])

    def at(self, time: float) -> np.ndarray:
        n = len(self.t)
        if self.loop:
            time = time % self.duration
        else:
            time = min(max(time, self.t[0]), self.t[-1])
        i = int(np.searchsorted(self.t, time, side="right")) - 1
        i = min(max(i, 0), n - 2)
        u = (time - self.t[i]) / (self.t[i + 1] - self.t[i])
        p1, p2 = self.v[i], self.v[i + 1]
        if self.mode == "linear":
            return lerp(p1, p2, u)
        if self.mode == "smooth":
            return lerp(p1, p2, smoothstep(u))

        # Catmull-Rom needs the neighbours p0 and p3
        if self.loop:
            # the last key duplicates the first one, so skip it when wrapping
            m = n - 1
            p0, p3 = self.v[(i - 1) % m], self.v[(i + 2) % m]
        else:
            p0 = self.v[max(i - 1, 0)]
            p3 = self.v[min(i + 2, n - 1)]
        return 0.5 * ((2 * p1) + (-p0 + p2) * u
                      + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


class Pendulum:
    """Periodic motion: damped simple harmonic oscillator  theta = A e^{-bt} cos(wt)."""

    def __init__(self, amplitude: float, omega: float, damping: float = 0.0):
        self.a, self.w, self.b = amplitude, omega, damping

    def angle(self, t: float) -> float:
        return self.a * math.exp(-self.b * t) * math.cos(self.w * t)


# =====================================================================
# MODULE 5 (extras) - motion specification for the user interface
# =====================================================================
def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


class Spring:
    """Damped harmonic oscillator used for every UI animation (selection pill, panels, switches).

        x'' = w^2 (target - x) - 2 z w x'          w = 2*pi*freq,  z = damping ratio

    z = 1 is critically damped (fastest settle, no overshoot); z < 1 overshoots a little, which is
    what gives the 'springy' Apple feel.  Integrated with small semi-implicit Euler sub-steps so it
    stays stable for any frame time.
    """

    def __init__(self, value: float = 0.0, freq: float = 4.0, damping: float = 0.8):
        self.x, self.v, self.target = float(value), 0.0, float(value)
        self.w, self.z = 2.0 * math.pi * freq, damping

    def update(self, dt: float) -> float:
        n = max(1, int(dt * 240.0) + 1)
        h = dt / n
        for _ in range(n):
            a = self.w * self.w * (self.target - self.x) - 2.0 * self.z * self.w * self.v
            self.v += a * h
            self.x += self.v * h
        return self.x

    def snap(self, value: float) -> None:
        self.x = self.target = float(value)
        self.v = 0.0

    @property
    def settled(self) -> bool:
        return abs(self.target - self.x) < 1e-3 and abs(self.v) < 1e-3


# =====================================================================
# Colour names (accessibility: the game never relies on colour alone)
# =====================================================================
HUE_NAMES = ["Red", "Orange", "Yellow", "Lime", "Green", "Mint",
             "Cyan", "Azure", "Blue", "Violet", "Magenta", "Rose"]


def hue_name(h: float) -> str:
    """Nearest of 12 named hues (30 degrees apart)."""
    return HUE_NAMES[int(((h % 360.0) + 15.0) // 30.0) % 12]
