#!/usr/bin/env python3
"""
L U M E N   D R I F T
=====================
You are a living point of light falling through an endless, bending tunnel.

  * Your orb IS the light source.  Every wall, pillar and gate is lit by YOU
    (a coloured Phong point light).  Energy = light radius: as it drains the world
    goes dark.  Collect shards to keep the light alive.
  * Your orb has a HUE (HSV colour model).  Spectrum Gates are colour filters:
    only an orb whose hue matches the gate may pass; any other colour shatters.
  * Red hazards (pillars, spinning spoke-wheels) must be dodged, never matched.
  * Space fires a sonar pulse that floods the tunnel ahead with light.

Run:   python lumen_drift.py          (see README.md for controls)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time as _time
from collections import OrderedDict, deque

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
from pygame.locals import (DOUBLEBUF, FULLSCREEN, K_1, K_6, K_DOWN, K_ESCAPE, K_F11, K_F12, K_LEFT, K_RETURN,
                           K_RIGHT, K_SPACE, K_TAB, K_UP, K_a, K_c, K_d, K_e, K_m, K_p, K_q, K_r, K_s, K_v, K_w,
                           KEYDOWN, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEMOTION, MOUSEWHEEL, OPENGL, QUIT, RESIZABLE,
                           VIDEORESIZE)
from OpenGL.GL import *  # noqa: F401,F403  (fixed-function OpenGL, as in the lab syllabus)

import gfxcore as gx
import postfx
import ui
from gamepad import Gamepad
from settings import DEFAULTS, QUALITIES, Settings

# --------------------------------------------------------------------------- constants
LH = 720                       # logical HUD height; logical width follows the window aspect
RING_DS = 2.5                  # distance between tunnel rings
NR, NSEG = 96, 40              # rings drawn / segments per ring
ORB_R = 0.55
HUE_TOL = 24.0                 # degrees a gate forgives
SIX = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
SIX_NAMES = ["R", "Y", "G", "C", "B", "M"]
MAXV = 15.0                    # max steering speed (units/s)
HAZARD = (1.0, 0.24, 0.10)
HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(HERE, "lumen_drift_save.json")
SETTINGS_PATH = os.path.join(HERE, "lumen_drift_settings.json")
FONT_DIR = os.path.join(HERE, "assets", "fonts")

COS = np.cos(np.linspace(0, 2 * np.pi, NSEG, endpoint=False))
SIN = np.sin(np.linspace(0, 2 * np.pi, NSEG, endpoint=False))


# --------------------------------------------------------------------------- the tunnel
def path_x(s):
    return 9.0 * np.sin(s * 0.0105) + 5.0 * np.sin(s * 0.0231 + 1.3) + 2.0 * np.sin(s * 0.047 + 0.4)


def path_y(s):
    return 4.5 * np.sin(s * 0.0087 + 0.7) + 2.8 * np.sin(s * 0.0193 + 2.1)


def tunnel_r(s):
    return 7.2 + 0.9 * np.sin(s * 0.031) + 0.5 * np.sin(s * 0.083 + 1.0)


def zone_hue(s):
    return (235.0 + 70.0 * np.sin(np.asarray(s) / 650.0)) % 360.0


def world_pos(s, u, v):
    """Tunnel coordinates (distance s, offset u/v from the centre line) -> world. Forward = -z."""
    return (float(path_x(s)) + u, float(path_y(s)) + v, -float(s))


def rgb(h, s=1.0, v=1.0):
    return gx.hsv_to_rgb(h, s, v)


def mixc(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# --------------------------------------------------------------------------- obstacles
class Pillar:
    kind = "pillar"

    def __init__(self, s, ang, length):
        self.s, self.ang, self.length = s, ang, length      # ang in radians around the axis
        self.width, self.depth, self.reveal = 1.7, 2.4, 0.0

    def hit(self, s0, s1, u, v):
        if s1 < self.s - self.depth / 2 - 0.2 or s0 > self.s + self.depth / 2 + 0.2:
            return False
        R = float(tunnel_r(self.s))
        ca, sa = math.cos(self.ang), math.sin(self.ang)
        x0, y0 = (R + 0.5) * ca, (R + 0.5) * sa                  # wall end
        x1, y1 = (R - self.length) * ca, (R - self.length) * sa  # tip
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((u - x0) * dx + (v - y0) * dy) / (dx * dx + dy * dy)))
        return math.hypot(u - (x0 + t * dx), v - (y0 + t * dy)) < self.width / 2 + ORB_R * 0.85


class Wheel:
    kind = "wheel"

    def __init__(self, s, th0, om, n):
        self.s, self.th0, self.om, self.n = s, th0, om, n
        self.thick, self.depth, self.reveal = 0.85, 1.1, 0.0

    def angles(self, t):
        return [self.th0 + self.om * t + i * 2 * math.pi / self.n for i in range(self.n)]

    def hit(self, s0, s1, u, v, t):
        if s1 < self.s - self.depth / 2 - 0.2 or s0 > self.s + self.depth / 2 + 0.2:
            return False
        R = float(tunnel_r(self.s))
        if math.hypot(u, v) < 0.9 + ORB_R * 0.6:
            return True                                           # the hub
        for a in self.angles(t):
            ca, sa = math.cos(a), math.sin(a)
            tt = max(0.0, min(R, u * ca + v * sa))
            if math.hypot(u - tt * ca, v - tt * sa) < self.thick / 2 + ORB_R * 0.85:
                return True
        return False


class Gate:
    kind = "gate"

    def __init__(self, s, hue):
        self.s, self.hue, self.state, self.flash, self.reveal = s, hue, "armed", 0.0, 0.0


class Shard:
    kind = "shard"

    def __init__(self, s, u, v, hue):
        self.s, self.u, self.v, self.hue, self.taken = s, u, v, hue, False


# --------------------------------------------------------------------------- particles
class Particles:
    def __init__(self, cap=1200):
        self.cap, self.i = cap, 0
        self.pos = np.zeros((cap, 3), np.float32)
        self.vel = np.zeros((cap, 3), np.float32)
        self.life = np.zeros(cap, np.float32)
        self.maxl = np.ones(cap, np.float32)
        self.col = np.ones((cap, 3), np.float32)

    def emit(self, p, n, speed, col, life=(0.5, 1.3), bias=(0, 0, 0)):
        idx = (self.i + np.arange(n)) % self.cap
        self.i = (self.i + n) % self.cap
        d = np.random.randn(n, 3)
        d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
        self.pos[idx] = p
        self.vel[idx] = d * speed * np.random.uniform(0.25, 1.0, (n, 1)) + np.asarray(bias)
        self.life[idx] = self.maxl[idx] = np.random.uniform(life[0], life[1], n)
        self.col[idx] = col

    def update(self, dt):
        alive = self.life > 0
        self.pos[alive] += self.vel[alive] * dt
        self.vel[alive] *= max(0.0, 1.0 - 1.8 * dt)
        self.life[alive] -= dt

    def draw(self, draw_points):
        a = self.life > 0
        if not a.any():
            return
        fade = (self.life[a] / self.maxl[a])[:, None]
        rgba = np.concatenate([self.col[a], fade ** 1.4], axis=1).astype(np.float32)
        draw_points(np.ascontiguousarray(self.pos[a]), rgba, 5.5, 2.4)


# --------------------------------------------------------------------------- procedural audio
class Audio:
    """Everything you hear is synthesised with NumPy at start-up - there are no audio files."""

    def __init__(self, enabled=True):
        self.ok, self.sfx, self.music, self.music_on = False, {}, None, True
        self.music_chan = None
        self.master, self.music_v, self.sfx_v = 0.85, 0.60, 0.90
        if not enabled:
            return
        try:
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
            self.sr = pygame.mixer.get_init()[0]
            self._build()
            self.ok = True
        except Exception as exc:                                         # no sound device: play silently
            print("[audio disabled]", exc)

    # ---- tiny synth kit
    def _t(self, d):
        return np.arange(int(d * self.sr)) / self.sr

    def _snd(self, st):
        arr = np.ascontiguousarray(np.clip(st, -1, 1) * 32000).astype(np.int16)
        return pygame.sndarray.make_sound(arr)

    @staticmethod
    def _pan(mono, p=0.0):
        return np.stack([mono * (1 - max(p, 0)), mono * (1 + min(p, 0))], axis=1)

    def _pluck(self, f, d, decay=7.0):
        t = self._t(d)
        return np.exp(-decay * t) * (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t)
                                     + 0.15 * np.sin(6 * np.pi * f * t)) * 0.55

    @staticmethod
    def _midi(m):
        return 440.0 * 2 ** ((m - 69) / 12.0)

    @staticmethod
    def _add_wrap(buf, start, sig):
        n = len(buf)
        start %= n
        k = min(len(sig), n - start)
        buf[start:start + k] += sig[:k]
        if k < len(sig):
            buf[:len(sig) - k] += sig[k:]

    def _build(self):
        sr = self.sr
        rng = np.random.default_rng(5)
        # --- music: 8 bars, Am - F - C - G, kick + bass + arp + pad, seamless loop
        bpm = 104.0
        beat = 60.0 / bpm
        total = int(round(32 * beat * sr))
        L, R = np.zeros(total), np.zeros(total)
        chords = [[45, 52, 57, 60, 64], [41, 48, 53, 57, 60], [48, 55, 60, 64, 67], [43, 50, 55, 59, 62]]
        for ci, ch in enumerate(chords):
            start = int(ci * 8 * beat * sr)
            dur = 8 * beat + 1.4
            t = self._t(dur)
            env = np.minimum(1, t / 1.1) * np.minimum(1, np.maximum(0, (dur - t)) / 1.3)
            for k, m in enumerate(ch):
                f = self._midi(m) * (1 + 0.0035 * (k % 3 - 1))
                sig = sum(np.sin(2 * np.pi * f * h * t) / h ** 1.4 for h in (1, 2, 3)) * env * 0.05
                self._add_wrap(L, start, sig * (0.8 + 0.2 * (k % 2)))
                self._add_wrap(R, start, sig * (0.8 + 0.2 * ((k + 1) % 2)))
            tones = [self._midi(m + 12) for m in ch[1:]]
            order = [0, 2, 3, 2, 1, 2, 3, 1]
            for step in range(32):                                           # 16th-note arpeggio
                f = tones[order[step % 8] % len(tones)]
                s0 = int((ci * 8 * beat + step * beat / 4) * sr)
                pl = self._pluck(f, 0.4, 9.0) * 0.17
                self._add_wrap(L, s0, pl * (0.4 + 0.6 * (step % 2)))
                self._add_wrap(R, s0, pl * (1.0 - 0.6 * (step % 2)))
            for step in range(16):                                           # 8th-note bass
                s0 = int((ci * 8 * beat + step * beat / 2) * sr)
                tb = self._t(0.34)
                b = np.sin(2 * np.pi * self._midi(ch[0]) * tb) * np.exp(-5 * tb) * 0.32
                self._add_wrap(L, s0, b)
                self._add_wrap(R, s0, b)
        for bt in range(32):                                                 # kick on every beat, hat on off-beats
            s0 = int(bt * beat * sr)
            tk = self._t(0.28)
            k = np.sin(2 * np.pi * np.cumsum(46 + 110 * np.exp(-tk * 22)) / sr) * np.exp(-tk * 9) * 0.42
            self._add_wrap(L, s0, k)
            self._add_wrap(R, s0, k)
            s1 = int((bt + 0.5) * beat * sr)
            th = self._t(0.06)
            h = np.diff(rng.standard_normal(len(th) + 1)) * np.exp(-th * 70) * 0.06
            self._add_wrap(L, s1, h)
            self._add_wrap(R, s1, h * 0.7)
        mus = np.stack([L, R], axis=1)
        mus /= max(1e-6, np.abs(mus).max()) / 0.8
        self.music = self._snd(mus)
        self.music_chan = None

        # --- sound effects
        pent = [659, 740, 880, 988, 1109, 1318, 1480, 1760]
        for i, f in enumerate(pent):
            a = self._pluck(f, 0.32, 9)
            b = np.concatenate([np.zeros(int(0.06 * sr)), self._pluck(f * 1.5, 0.3, 9)])
            n = max(len(a), len(b))
            a, b = np.pad(a, (0, n - len(a))), np.pad(b, (0, n - len(b)))
            self.sfx[f"shard{i}"] = self._snd(self._pan((a + b) * 0.6))
        n = int(0.9 * sr)
        mix = np.zeros(n)
        for k, f in enumerate([523, 659, 784, 1047, 1319]):
            tt = self._t(0.9)
            mix += np.pad(np.exp(-3 * tt) * np.sin(2 * np.pi * f * tt), (int(k * 0.05 * sr), 0))[:n] * 0.3
        self.sfx["gate_ok"] = self._snd(self._pan(mix))
        tt = self._t(0.55)
        buz = (np.sign(np.sin(2 * np.pi * 110 * tt)) + np.sign(np.sin(2 * np.pi * 117 * tt))) * 0.2 * np.exp(-4 * tt)
        self.sfx["gate_fail"] = self._snd(self._pan(buz + rng.standard_normal(len(tt)) * 0.08 * np.exp(-9 * tt)))
        tt = self._t(0.7)
        noise = np.convolve(rng.standard_normal(len(tt)), np.ones(14) / 14, mode="same")
        crash = noise * np.exp(-5 * tt) * 1.3 + np.sin(2 * np.pi * np.cumsum(150 * np.exp(-tt * 4) + 38) / sr) * np.exp(-4 * tt) * 0.8
        self.sfx["crash"] = self._snd(self._pan(crash * 0.7))
        tt = self._t(1.1)
        sweep = np.sin(2 * np.pi * np.cumsum(180 * np.exp(tt * 3.0)) / sr) * np.exp(-2.6 * tt) * 0.45
        self.sfx["pulse"] = self._snd(self._pan(sweep))
        tt = self._t(0.06)
        self.sfx["click"] = self._snd(self._pan(np.sin(2 * np.pi * 1300 * tt) * np.exp(-40 * tt) * 0.5))
        tt = self._t(0.18)
        self.sfx["beep"] = self._snd(self._pan(np.sin(2 * np.pi * 520 * tt) * np.exp(-12 * tt) * 0.5))
        tt = self._t(0.7)
        self.sfx["go"] = self._snd(self._pan(np.sin(2 * np.pi * 1040 * tt) * np.exp(-5 * tt) * 0.5
                                             + np.sin(2 * np.pi * 1560 * tt) * np.exp(-6 * tt) * 0.25))
        tt = self._t(1.8)
        down = np.sin(2 * np.pi * np.cumsum(520 * np.exp(-tt * 1.3)) / sr) * np.exp(-1.6 * tt) * 0.55
        self.sfx["over"] = self._snd(self._pan(down))

    def set_volumes(self, master, music, sfx):
        self.master, self.music_v, self.sfx_v = master, music, sfx
        self._apply_music()

    def _apply_music(self):
        if self.ok and self.music is not None:
            self.music.set_volume(min(1.0, self.master * self.music_v) if self.music_on else 0.0)

    def play(self, name, vol=1.0):
        if self.ok and name in self.sfx:
            s = self.sfx[name]
            s.set_volume(max(0.0, min(1.0, vol * self.master * self.sfx_v / 0.765)))
            s.play()

    def start_music(self):
        if self.ok and self.music_chan is None:
            self.music_chan = self.music.play(loops=-1)
            self._apply_music()

    def toggle_music(self):
        self.music_on = not self.music_on
        self._apply_music()


# --------------------------------------------------------------------------- text
class Text:
    """Inter (bundled, OFL) -> cached GL textures drawn as tinted quads.
    Glyphs are rasterised at the real pixel size (logical size x HiDPI scale) so text stays razor sharp on Retina."""

    FILES = {"light": "InterDisplay-Light.otf", "regular": "Inter-Regular.otf",
             "medium": "Inter-Medium.otf", "semibold": "Inter-SemiBold.otf"}

    def __init__(self):
        self.paths = {}
        for w, fn in self.FILES.items():
            p = os.path.join(FONT_DIR, fn)
            if os.path.isfile(p):
                self.paths[w] = p
        self.fallback = None
        if not self.paths:                                  # fonts missing: use any system font
            for name in ("helveticaneue", "avenir", "segoeui", "arial", "dejavusans", "verdana"):
                p = pygame.font.match_font(name)
                if p:
                    self.fallback = p
                    break
        self.ps = 1.0
        self.fonts, self.cache = {}, OrderedDict()

    def _font(self, px, weight):
        key = (px, weight)
        if key not in self.fonts:
            path = self.paths.get(weight) or self.paths.get("medium") or self.fallback
            try:
                self.fonts[key] = pygame.font.Font(path, px) if path else pygame.font.Font(None, int(px * 1.35))
            except Exception:
                self.fonts[key] = pygame.font.Font(None, int(px * 1.35))
        return self.fonts[key]

    def get(self, text, size, tracking, weight="medium"):
        px = max(6, int(round(size * self.ps)))
        trk = int(round(tracking * self.ps))
        key = (text, px, trk, weight)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        f = self._font(px, weight)
        if trk:
            parts = [f.render(c, True, (255, 255, 255)) for c in text]
            w = sum(p.get_width() for p in parts) + trk * (len(parts) - 1)
            surf = pygame.Surface((max(w, 1), f.get_height()), pygame.SRCALPHA)
            x = 0
            for p in parts:
                surf.blit(p, (x, 0))
                x += p.get_width() + trk
        else:
            surf = f.render(text if text else " ", True, (255, 255, 255))
        surf = surf.convert_alpha()
        w, h = surf.get_size()
        data = pygame.image.tostring(surf, "RGBA", True)
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        self.cache[key] = (tex, w / self.ps, h / self.ps)          # sizes are LOGICAL units
        if len(self.cache) > 400:
            _, (old, _, _) = self.cache.popitem(last=False)
            glDeleteTextures([old])
        return self.cache[key]

    def width(self, text, size, tracking=0, weight="medium"):
        return self.get(text, size, tracking, weight)[1]

    def draw(self, text, x, y, size, color=(1, 1, 1), a=1.0, align="l", tracking=0, scale=1.0, shadow=True,
             weight="medium"):
        """x = anchor (left/centre/right), y = vertical centre; logical HUD units."""
        tex, w, h = self.get(text, size, tracking, weight)
        w, h = w * scale, h * scale
        x0 = x - (w / 2 if align == "c" else w if align == "r" else 0)
        y0 = y - h / 2
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex)
        for dx, dy, col, al in ((1.5, 1.5, (0, 0, 0), 0.5 * a), (0, 0, color, a)) if shadow else ((0, 0, color, a),):
            glColor4f(col[0], col[1], col[2], al)
            glBegin(GL_QUADS)
            glTexCoord2f(0, 1); glVertex2f(x0 + dx, y0 + dy)
            glTexCoord2f(1, 1); glVertex2f(x0 + w + dx, y0 + dy)
            glTexCoord2f(1, 0); glVertex2f(x0 + w + dx, y0 + h + dy)
            glTexCoord2f(0, 0); glVertex2f(x0 + dx, y0 + h + dy)
            glEnd()
        glDisable(GL_TEXTURE_2D)


# --------------------------------------------------------------------------- the game
class Game:
    def __init__(self, args):
        self.args = args
        pygame.init()
        self.settings = Settings(None if args.no_save else (args.settings or SETTINGS_PATH))
        if args.classic:
            self.settings["quality"] = "classic"
        elif args.quality:
            self.settings["quality"] = args.quality
        self.audio = Audio(enabled=not args.mute)
        self.apply_audio()
        self.size = tuple(int(v) for v in args.size.lower().split("x"))
        self.fullscreen = bool(self.settings["fullscreen"]) and not args.autoplay and not args.shots
        self.fx = None
        self.fx_error = None
        self.rr = None
        self._make_display()
        self.running = True
        self.rng = random.Random(args.seed)
        np.random.seed(args.seed)
        self.best = self._load_best()
        self.show_lab = False
        self.ortho_cam = False
        self.cam_mode = 0
        self.mouse = (-1, -1)
        self.frame = 0
        self.fps = 60.0
        self.clock_t = 0.0
        self.particles = Particles()
        self.mote_base = np.random.rand(380)
        self.mote_ang = np.random.rand(380) * 2 * math.pi
        self.mote_rad = np.sqrt(np.random.rand(380))
        self.sline_ang = np.random.rand(48) * 2 * math.pi
        self.sline_ph = np.random.rand(48)
        self.title_cam = gx.Track([
            (0.0, (0.0, 1.2, 9.0, 18.0, 70.0, 0.0)),
            (4.0, (4.2, 0.6, 6.0, 8.0, 64.0, 7.0)),
            (8.0, (-3.2, 2.4, 14.0, 20.0, 80.0, -6.0)),
            (12.0, (0.5, -1.8, 5.0, 24.0, 90.0, 3.0)),
            (16.0, (0.0, 1.2, 9.0, 18.0, 70.0, 0.0))], mode="catmull", loop=True)
        self.mode = "title"
        self.screen = None                          # None | "settings" | "controls" (overlays on title / pause)
        self.screen_from = "title"
        self.input_dev = "kbd"                      # last device used: shows the right hints
        self.fade = 1.0                             # fade-in from black
        self.gamepad = Gamepad(use_hardware=not (args.autoplay or args.shots))
        self._key_repeat = False
        self.build_menus()
        self.reset_world(attract=True)
        if args.autoplay:
            self.start_run(autopilot=True)
        self.audio.start_music()

    # ------------------------------------------------------------ settings plumbing
    def set_setting(self, key, value):
        old = self.settings[key]
        self.settings[key] = value
        new = self.settings[key]
        if new == old:
            return
        if key in ("master_vol", "music_vol", "sfx_vol"):
            self.apply_audio()
        elif key == "quality":
            self.apply_quality()
        elif key == "fullscreen":
            self.fullscreen = bool(new)
            self._make_display()
        elif key == "rumble" and new:
            self.gamepad.rumble(0.5, 160)

    def apply_quality(self):
        if bool(self._ms_requested) != bool(self.settings.profile()["msaa"]):
            self._make_display()                    # Classic wants a multisampled window, Premium does not
        else:
            self.init_renderer()

    def reset_settings(self):
        fs = self.settings["fullscreen"]
        q = self.settings["quality"]
        self.settings.reset()
        self.apply_audio()
        if self.settings["fullscreen"] != fs:
            self.fullscreen = bool(self.settings["fullscreen"])
            self._make_display()
        elif self.settings["quality"] != q:
            self.apply_quality()
        self.audio.play("click")

    def close_screen(self):
        if self.screen == "settings":
            self.settings.save()
        self.screen = None
        self.audio.play("click", 0.5)

    def open_screen(self, name):
        self.screen = name
        if name == "settings":
            self.menu_settings.reset_focus()
            self.menu_settings.tab = 0
        self.audio.play("click", 0.6)

    def build_menus(self):
        st = self.settings

        def S(key):
            return (lambda: st[key]), (lambda v: self.set_setting(key, v))

        pct = lambda v: f"{int(round(v * 100))}%"
        has_fx = lambda: self.fx is not None
        Q = [("classic", "Classic"), ("balanced", "Balanced"), ("premium", "Premium"), ("ultra", "Ultra")]
        gfx = [ui.Item("choice", "Graphics quality", *S("quality"), choices=Q),
               ui.Item("slider", "Bloom", *S("bloom"), lo=0.0, hi=1.6, step=0.1, fmt=lambda v: f"{v:.1f}", enabled=has_fx),
               ui.Item("toggle", "Film grain", *S("film_grain"), enabled=has_fx),
               ui.Item("toggle", "Motion effects", *S("motion_fx")),
               ui.Item("slider", "Field of view", *S("fov"), lo=55.0, hi=95.0, step=2.0, fmt=lambda v: f"{int(round(v))} deg"),
               ui.Item("toggle", "Fullscreen", *S("fullscreen")),
               ui.Item("toggle", "Show FPS", *S("show_fps"))]
        aud = [ui.Item("slider", "Master volume", *S("master_vol"), step=0.05, fmt=pct),
               ui.Item("slider", "Music", *S("music_vol"), step=0.05, fmt=pct),
               ui.Item("slider", "Sound effects", *S("sfx_vol"), step=0.05, fmt=pct)]
        game = [ui.Item("toggle", "Colour-blind labels", *S("colorblind")),
                ui.Item("toggle", "Controller vibration", *S("rumble")),
                ui.Item("slider", "Steering speed", *S("steer_sens"), lo=0.6, hi=1.5, step=0.05, fmt=lambda v: f"{v:.2f}x"),
                ui.Item("gap"),
                ui.Item("button", "Reset to defaults", action=self.reset_settings, hint="danger")]
        self.menu_settings = ui.Menu("Settings", tabs=[("Graphics", gfx), ("Audio", aud), ("Gameplay", game)],
                                     footer=[ui.Item("button", "Done", action=self.close_screen)], form=True)
        self.menu_main = ui.Menu("", [ui.Item("button", "PLAY", action=lambda: self.start_run(autopilot=False)),
                                      ui.Item("button", "SETTINGS", action=lambda: self.open_screen("settings")),
                                      ui.Item("button", "CONTROLS", action=lambda: self.open_screen("controls")),
                                      ui.Item("button", "QUIT", action=lambda: setattr(self, "running", False))])
        self.menu_pause = ui.Menu("", [ui.Item("button", "RESUME", action=self.resume),
                                       ui.Item("button", "RESTART", action=lambda: self.start_run(autopilot=False)),
                                       ui.Item("button", "SETTINGS", action=lambda: self.open_screen("settings")),
                                       ui.Item("button", "QUIT TO MENU", action=self.to_title)])
        self.menu_over = ui.Menu("", [ui.Item("button", "RETRY", action=lambda: self.start_run(autopilot=False)),
                                      ui.Item("button", "MENU", action=self.to_title)], width=300)

    def active_menu(self):
        if self.screen == "settings":
            return self.menu_settings
        if self.screen == "controls":
            return None
        if self.mode == "title":
            return self.menu_main
        if self.mode == "paused":
            return self.menu_pause
        if self.mode == "over" and self.over_t > 1.0:
            return self.menu_over
        return None

    # ---- shared glass drawing (rounded, frosted, anti-aliased when shaders are available)
    def glass(self, x, y, w, h, r, fill, border=(0, 0, 0, 0), a=1.0, shadow=0.0):
        if a <= 0.002:
            return
        if self.rr is not None:
            bd, gl = None, 0.0
            if self.fx is not None and self.fx.backdrop_ready:
                bd, gl = self.fx.bd[0].tex, 1.0
            else:
                fill = (fill[0], fill[1], fill[2], min(0.94, fill[3] + 0.32))     # no blurred backdrop: be more opaque
            self.rr.draw(x, y, w, h, r, fill, border, glass=gl, shadow=shadow, px=1.0 / self.ps, res=self.size,
                         backdrop=bd, alpha=a)
        else:
            glColor4f(fill[0], fill[1], fill[2], min(1.0, fill[3] + 0.2) * a)
            glRectf(x, y, x + w, y + h)

    def panel(self, x, y, w, h, r=26, a=1.0, shadow=1.0):
        self.glass(x, y, w, h, r, (0.05, 0.07, 0.13, 0.46), (1, 1, 1, 0.17), a, shadow)

    def chip(self, x, y, text, a=1.0, col=(0.7, 0.92, 1.0)):
        """A small rounded 'key cap'. Returns its width."""
        w = self.text.width(text, 15, 1, "semibold") + 22
        self.glass(x, y - 15, w, 30, 9, (0.12, 0.16, 0.24, 0.7), (1, 1, 1, 0.22), a)
        self.text.draw(text, x + w / 2, y + 1, 15, col, a, "c", 1, shadow=False, weight="semibold")
        return w

    # ------------------------------------------------------------ display / GL setup
    def _make_display(self):
        flags = DOUBLEBUF | OPENGL | RESIZABLE
        if self.fullscreen:
            flags = DOUBLEBUF | OPENGL | FULLSCREEN
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
        want_ms = self.settings.profile()["msaa"]
        self._ms_requested = want_ms
        for ms in ((want_ms, 0) if want_ms else (0,)):
            try:
                pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1 if ms else 0)
                pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, ms)
                pygame.display.set_mode((0, 0) if self.fullscreen else self.size, flags, vsync=1 if not self.args.novsync else 0)
                break
            except Exception:
                if ms == 0:
                    raise
        pygame.display.set_caption("LUMEN DRIFT  -  BCS501 OpenGL")
        self.win_size = pygame.display.get_surface().get_size()
        vp = glGetIntegerv(GL_VIEWPORT)                      # real drawable size (differs from window size on Retina / HiDPI)
        self.size = (int(vp[2]), int(vp[3])) if vp[2] > 0 and vp[3] > 0 else self.win_size
        self.init_gl()

    def apply_audio(self):
        st = self.settings
        self.audio.set_volumes(st["master_vol"], st["music_vol"], st["sfx_vol"])

    def init_renderer(self):
        """(Re)build the Premium pipeline for the current size/quality; any failure falls back to Classic."""
        if self.fx is not None:
            try:
                self.fx.free()
            except Exception:
                pass
        self.fx = None
        prof = self.settings.profile()
        if prof["premium"]:
            try:
                self.fx = postfx.PostFX(self.size, prof["scale"], prof["bloom_levels"])
                self.fx_error = None
            except Exception as exc:                         # no FBO / shader support: stay on the fixed-function path
                self.fx, self.fx_error = None, str(exc).splitlines()[0] if str(exc) else repr(exc)
                print("[premium renderer unavailable - using Classic]", self.fx_error)
        try:
            self.rr = postfx.RoundRect()
        except Exception as exc:
            self.rr = None
            print("[glass UI shader unavailable - using flat panels]", exc)
        self.ps3 = self.ps * (self.fx.scale if self.fx else 1.0)

    def init_gl(self):
        glViewport(0, 0, *self.size)
        self.LW = LH * self.size[0] / self.size[1]
        self.ps = self.size[1] / LH
        self.ps3 = self.ps
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_NORMALIZE)
        glEnable(GL_LINE_SMOOTH)
        glEnable(GL_POINT_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
        try:
            glEnable(GL_MULTISAMPLE)
        except Exception:
            pass
        glShadeModel(GL_SMOOTH)
        glClearColor(0.004, 0.006, 0.016, 1.0)
        glEnable(GL_FOG)
        glFogi(GL_FOG_MODE, GL_EXP2)
        glFogfv(GL_FOG_COLOR, (0.0, 0.0, 0.0, 1.0))
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.03, 0.035, 0.05, 1.0))
        try:
            glPointParameterfv(GL_POINT_DISTANCE_ATTENUATION, (1.0, 0.0, 0.0016))
        except Exception:
            pass
        self.glow_tex = self._radial_texture(64, 2.2, False)
        self.vig_tex = self._radial_texture(128, 2.0, True)
        self._build_lists()
        self._build_tunnel_indices()
        self.text = Text() if not hasattr(self, "text") else self.text
        self.text.cache.clear()                       # GL textures die with a context rebuild
        self.text.ps = self.ps
        self.init_renderer()
        self.build_hud()

    def _radial_texture(self, n, power, vignette):
        ys, xs = np.mgrid[0:n, 0:n]
        d = np.hypot(xs - (n - 1) / 2, ys - (n - 1) / 2) / ((n - 1) / 2)
        a = np.clip((d - 0.45) / 0.65, 0, 1) ** power if vignette else np.clip(1 - d, 0, 1) ** power
        rgba = np.empty((n, n, 4), np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = (a * 255).astype(np.uint8)
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, n, n, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba)
        return tex

    def _build_lists(self):
        L = self.lists = {}
        faces = [((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
                 ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
                 ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
                 ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
                 ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
                 ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)])]
        L["cube"] = glGenLists(1)
        glNewList(L["cube"], GL_COMPILE)
        glBegin(GL_QUADS)
        for n, vs in faces:
            glNormal3f(*n)
            for v in vs:
                glVertex3f(v[0] * 0.5, v[1] * 0.5, v[2] * 0.5)
        glEnd()
        glEndList()
        L["edges"] = glGenLists(1)
        glNewList(L["edges"], GL_COMPILE)
        glBegin(GL_LINES)
        for a in (-0.5, 0.5):
            for b in (-0.5, 0.5):
                glVertex3f(-0.5, a, b); glVertex3f(0.5, a, b)
                glVertex3f(a, -0.5, b); glVertex3f(a, 0.5, b)
                glVertex3f(a, b, -0.5); glVertex3f(a, b, 0.5)
        glEnd()
        glEndList()
        L["sphere"] = glGenLists(1)
        glNewList(L["sphere"], GL_COMPILE)
        stacks, slices = 14, 26
        for i in range(stacks):
            p0, p1 = math.pi * i / stacks - math.pi / 2, math.pi * (i + 1) / stacks - math.pi / 2
            glBegin(GL_QUAD_STRIP)
            for j in range(slices + 1):
                th = 2 * math.pi * j / slices
                for p in (p1, p0):
                    x, y, z = math.cos(p) * math.cos(th), math.sin(p), math.cos(p) * math.sin(th)
                    glNormal3f(x, y, z)
                    glVertex3f(x, y, z)
            glEnd()
        glEndList()
        L["octa"] = glGenLists(1)
        glNewList(L["octa"], GL_COMPILE)
        glBegin(GL_TRIANGLES)
        for sx in (1, -1):
            for sy in (1, -1):
                for sz in (1, -1):
                    n = np.array([sx, sy, sz], float) / math.sqrt(3)
                    glNormal3f(*n)
                    glVertex3f(sx, 0, 0); glVertex3f(0, sy, 0); glVertex3f(0, 0, sz)
        glEnd()
        glEndList()
        L["ring"] = glGenLists(1)
        glNewList(L["ring"], GL_COMPILE)
        glBegin(GL_LINE_LOOP)
        for i in range(72):
            a = 2 * math.pi * i / 72
            glVertex3f(math.cos(a), math.sin(a), 0)
        glEnd()
        glEndList()
        L["disc"] = glGenLists(1)
        glNewList(L["disc"], GL_COMPILE)
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(0, 0, 0)
        for i in range(73):
            a = 2 * math.pi * i / 72
            glVertex3f(math.cos(a), math.sin(a), 0)
        glEnd()
        glEndList()

    def _build_tunnel_indices(self):
        idx, ring_even, ring_odd, longi = [], [], [], []
        for i in range(NR - 1):
            for j in range(NSEG):
                a, b = i * NSEG + j, i * NSEG + (j + 1) % NSEG
                c, d = (i + 1) * NSEG + j, (i + 1) * NSEG + (j + 1) % NSEG
                idx += [a, c, b, b, c, d]
                if j % 2 == 0:
                    longi += [a, c]
        for i in range(NR):
            tgt = ring_even if i % 2 == 0 else ring_odd
            for j in range(NSEG):
                tgt += [i * NSEG + j, i * NSEG + (j + 1) % NSEG]
        self.t_idx = np.array(idx, np.uint32)
        self.t_ring = (np.array(ring_even, np.uint32), np.array(ring_odd, np.uint32))
        self.t_long = np.array(longi, np.uint32)
        self.t_norm = np.ascontiguousarray(np.tile(np.stack([-COS, -SIN, np.zeros(NSEG)], axis=1), (NR, 1)), np.float32)

    # ------------------------------------------------------------ HUD geometry (built with OUR Bresenham / DDA)
    def build_hud(self):
        LW = self.LW
        self.hud = {}
        # hue wheel: three Bresenham circles, each pixel coloured by its angle (HSV hue)
        self.wheel_c = (112.0, LH - 128.0)
        pts, cols = [], []
        for r in (60, 61, 62, 63, 46, 47):
            for (x, y) in gx.bresenham_circle(0, 0, r):
                hue = (math.degrees(math.atan2(x, -y))) % 360.0
                pts.append((x, y))
                cols.append((*gx.hsv_to_rgb(hue, 1.0, 1.0), 0.95 if r > 50 else 0.45))
        self.hud["wheel"] = (np.array(pts, np.float32), np.array(cols, np.float32))
        # energy bar: DDA tick marks
        self.bar = (LW / 2 - 197.0, 34.0, 460.0, 16.0)
        bx, by, bw, bh = self.bar
        ticks = []
        for k in range(1, 10):
            x = int(bw * k / 10)
            ticks += gx.dda_line(x, int(bh) + 3, x, int(bh) + 9 if k % 5 else int(bh) + 13)
        self.hud["bar_ticks"] = np.array(ticks, np.float32) + (bx, by)
        # radar window frame
        self.radar = (LW - 258.0, LH - 258.0, 232.0, 232.0)
        rx, ry, rw, rh = self.radar
        rf = (gx.bresenham_line(0, 0, int(rw), 0) + gx.bresenham_line(int(rw), 0, int(rw), int(rh)) +
              gx.bresenham_line(int(rw), int(rh), 0, int(rh)) + gx.bresenham_line(0, int(rh), 0, 0))
        self.hud["radar_frame"] = np.array(rf, np.float32) + (rx, ry)

    # ------------------------------------------------------------ world state
    def reset_world(self, attract=False):
        self.attract = attract
        self.s = 0.0
        self.u = self.v = self.vu = self.vv = 0.0
        self.hue, self.hue_goal = 200.0, None
        self.energy = 100.0
        self.score = 0.0
        self.chain = 0
        self.gates_ok = 0
        self.shards_got = 0
        self.t_run = 0.0
        self.time = 0.0
        self.slow = 1.0
        self.speed = 22.0
        self.invuln = 0.0
        self.flash = (0.0, (1, 1, 1))
        self.shake = 0.0
        self.pulse_cd = 0.0
        self.pulse_t = 99.0
        self.wave_s = -1e9
        self.light_boost = 0.0
        self.toasts = []
        self.obs = []
        self.next_spawn = 70.0
        self.trail = deque(maxlen=120)
        self.particles.life[:] = 0
        self.prev_s = 0.0
        self.countdown = 0.0
        self.over_t = 0.0
        self.cam_blend = 0.0
        self.autopilot_on = attract
        self.new_best = False
        self.spawn_ahead()

    def start_run(self, autopilot=False):
        self.screen = None
        self.fade = 0.9
        self.reset_world(attract=False)
        self.autopilot_on = autopilot
        self.mode = "countdown"
        self.countdown = 3.0
        self._cd_last = 4
        self.cam_blend = 0.0
        self.audio.play("click")

    # ---- procedural level generation (endless, difficulty rises with distance)
    def spawn_ahead(self):
        while self.next_spawn < self.s + 260:
            self.spawn_piece(self.next_spawn)

    def spawn_piece(self, s0):
        d = min(1.0, s0 / 5200.0)
        r = self.rng
        kinds = ["pillars", "pillars", "wheel", "gate", "gate", "helix"] if s0 > 150 else ["pillars", "helix", "gate"]
        k = r.choice(kinds)
        length = 20.0
        if k == "pillars":
            if r.random() < 0.5:                                    # slalom
                n = r.randint(3, 4 + int(d * 2))
                ang = r.uniform(0, 2 * math.pi)
                for i in range(n):
                    L = r.uniform(3.0, 4.2 + d * 0.5)
                    self.obs.append(Pillar(s0 + i * 9.5, ang, L))
                    nxt = ang + math.pi + r.uniform(-0.7, 0.7)
                    mid = ang + math.pi
                    self.obs.append(Shard(s0 + i * 9.5 + 4.7, 3.4 * math.cos(mid), 3.4 * math.sin(mid), r.choice(SIX)))
                    ang = nxt
                length = n * 9.5
            else:                                                   # ring of pillars: thread the needle
                n = 3 if d < 0.5 else 4
                base = r.uniform(0, 2 * math.pi)
                for i in range(n):
                    self.obs.append(Pillar(s0, base + i * 2 * math.pi / n, 4.6 + 0.4 * d))
                for i in range(4):
                    self.obs.append(Shard(s0 - 6 + i * 2.0, 0, 0, r.choice(SIX)))
                length = 12.0
        elif k == "wheel":
            n = r.choice([2, 3, 3, 4] if d < 0.5 else [3, 4, 4, 5])
            om = (r.choice([-1, 1])) * (0.8 + 1.1 * d * r.random() + r.random() * 0.3)
            self.obs.append(Wheel(s0, r.uniform(0, 6.28), om, n))
            for i in range(3):
                self.obs.append(Shard(s0 - 9 + i * 3, 0, 0, r.choice(SIX)))
            length = 14.0
        elif k == "gate":
            pool = SIX if d < 0.45 else [h * 30.0 for h in range(12)]
            hue = r.choice(pool)
            for i in range(5):                                      # colour cue: shards in the gate's own hue
                a = i * 1.26
                self.obs.append(Shard(s0 + i * 3.4, 2.3 * math.cos(a), 2.3 * math.sin(a), hue))
            self.obs.append(Gate(s0 + 27.0, hue))
            length = 30.0
        else:                                                       # helix reward
            a0 = r.uniform(0, 6.28)
            for i in range(16):
                a = a0 + i * 0.55
                self.obs.append(Shard(s0 + i * 2.6, 3.6 * math.cos(a), 3.6 * math.sin(a), r.choice(SIX)))
            length = 42.0
        self.next_spawn = s0 + length + (36.0 - 16.0 * d) + r.uniform(0, 10)

    # ------------------------------------------------------------ autopilot (attract mode + --autoplay tests)
    def autopilot(self):
        s, u, v = self.s, self.u, self.v
        ahead = sorted([o for o in self.obs if o.kind != "shard" and s - 0.4 < o.s < s + 70], key=lambda o: o.s)
        goal_hue, tu, tv, have_target = None, 3.0 * math.sin(self.time * 0.9), 1.8 * math.cos(self.time * 0.7), False
        for o in ahead:
            if o.kind == "gate" and o.s - s < 55 and goal_hue is None and o.state == "armed":
                goal_hue = o.hue
        haz = [o for o in ahead if o.kind in ("pillar", "wheel")]
        if haz and haz[0].s - s < 52:
            o0 = haz[0]
            grp = [o for o in haz if abs(o.s - o0.s) < 4.0]
            if o0.kind == "pillar":
                angs = [p.ang for p in grp]
                best, bd = 0.0, -1.0
                for k in range(48):
                    a = k * 2 * math.pi / 48
                    md = min(abs(((a - b + math.pi) % (2 * math.pi)) - math.pi) for b in angs)
                    if md > bd:
                        best, bd = a, md
                r = 3.4 if len(angs) > 1 else 3.6
                tu, tv, have_target = r * math.cos(best), r * math.sin(best), True
            else:
                t_arr = (o0.s - s) / max(self.speed, 1.0)
                sp = sorted(a % (2 * math.pi) for a in o0.angles(self.time + t_arr))
                gaps = [((sp[i] + (sp[(i + 1) % len(sp)] + (2 * math.pi if i == len(sp) - 1 else 0))) / 2) for i in range(len(sp))]
                cur = math.atan2(v, u) % (2 * math.pi)
                g = min(gaps, key=lambda a: abs(((a - cur + math.pi) % (2 * math.pi)) - math.pi))
                tu, tv, have_target = 4.3 * math.cos(g), 4.3 * math.sin(g), True
        if not have_target:
            sh = [o for o in self.obs if o.kind == "shard" and not o.taken and s + 1.0 < o.s < s + 38]
            if sh:
                o = min(sh, key=lambda o: o.s)
                tu, tv = o.u, o.v
        ax = max(-1.0, min(1.0, (tu - u) * 0.9))
        ay = max(-1.0, min(1.0, (tv - v) * 0.9))
        return ax, ay, goal_hue

    # ------------------------------------------------------------ simulation
    def toast(self, text, color=(1, 1, 1), dur=1.4):
        for t in self.toasts:                       # same message again -> refresh it instead of stacking
            if t[0] == text:
                t[2] = t[3] = dur
                return
        self.toasts.append([text, color, dur, dur])

    def base_speed(self):
        return 24.0 + 34.0 * (1.0 - math.exp(-self.t_run / 100.0))

    def step(self, dt, keys):
        self.fade = max(0.0, self.fade - 2.2 * dt)
        menu = self.active_menu()
        if menu is not None:
            menu.update(dt)
            if not self.args.autoplay:
                for a_ in self.gamepad.update(dt):                    # held left stick navigates menus
                    self.input_dev = "pad"
                    self.do_action(a_)
        if self.mode == "paused":                                      # the world holds still behind the pause menu
            return
        self.time += dt
        m = self.mode
        live = m in ("play", "countdown")
        ax = ay = 0.0
        hue_dir = 0
        goal = None
        if self.autopilot_on and m in ("title", "play", "countdown"):
            ax, ay, goal = self.autopilot()
        elif live and not self.screen and m != "paused":
            ax = float(keys[K_RIGHT] or keys[K_d]) - float(keys[K_LEFT] or keys[K_a])
            ay = float(keys[K_UP] or keys[K_w]) - float(keys[K_DOWN] or keys[K_s])
            hue_dir = float(bool(keys[K_e])) - float(bool(keys[K_q]))
            if self.gamepad.present:
                px, py = self.gamepad.steer()
                ax = max(-1.0, min(1.0, ax + px))
                ay = max(-1.0, min(1.0, ay + py))
                hue_dir = max(-1.0, min(1.0, hue_dir + self.gamepad.hue_rate()))
        if m == "over":
            ax = ay = 0.0

        # steering with inertia, clamped to the tunnel wall
        k = min(1.0, 10.0 * dt)
        vmax = MAXV * self.settings["steer_sens"]
        self.vu += (ax * vmax - self.vu) * k
        self.vv += (ay * vmax - self.vv) * k
        self.u += self.vu * dt
        self.v += self.vv * dt
        rmax = float(tunnel_r(self.s)) - ORB_R - 0.45
        rr = math.hypot(self.u, self.v)
        if rr > rmax:
            nx, ny = self.u / rr, self.v / rr
            self.u, self.v = nx * rmax, ny * rmax
            dot = self.vu * nx + self.vv * ny
            if dot > 0:
                self.vu -= dot * nx
                self.vv -= dot * ny

        # hue control (HSV colour model)
        if hue_dir:
            self.hue = (self.hue + hue_dir * 240.0 * dt) % 360.0
            self.hue_goal = None
        if goal is not None:
            self.hue_goal = goal
        if self.hue_goal is not None:
            diff = ((self.hue_goal - self.hue + 180.0) % 360.0) - 180.0
            stepd = 720.0 * dt
            if abs(diff) <= stepd:
                self.hue, self.hue_goal = self.hue_goal % 360.0, None
            else:
                self.hue = (self.hue + math.copysign(stepd, diff)) % 360.0

        # forward motion
        if m == "countdown":
            self.countdown -= dt
            n = int(math.ceil(self.countdown))
            if n < self._cd_last and n >= 1:
                self._cd_last = n
                self.audio.play("beep")
            if self.countdown <= 0:
                self.mode = "play"
                self.audio.play("go")
                self.toast("DRIFT", (1, 1, 1), 1.0)
            fac = 0.35 + 0.65 * gx.smoothstep(1.0 - self.countdown / 3.0)
        elif m == "over":
            fac = max(0.0, 1.0 - self.over_t / 1.6)
        else:
            fac = 1.0
        if m in ("play", "title", "countdown"):
            self.t_run += dt
        self.slow = min(1.0, self.slow + 0.4 * dt)
        self.speed += (self.base_speed() * self.slow * fac - self.speed) * min(1.0, 2.5 * dt)
        self.prev_s = self.s
        self.s += self.speed * dt
        self.spawn_ahead()
        self.obs = [o for o in self.obs if o.s > self.s - 25.0]
        self.trail.append((self.s, world_pos(self.s, self.u, self.v)))
        if m in ("play", "title"):
            self.score += self.speed * dt * 0.4

        # timers
        self.invuln = max(0.0, self.invuln - dt)
        self.shake = max(0.0, self.shake - 2.2 * dt)
        self.light_boost = max(0.0, self.light_boost - 0.75 * dt)
        self.pulse_cd = max(0.0, self.pulse_cd - dt)
        self.pulse_t += dt
        if self.pulse_t < 1.3:
            self.wave_s += 175.0 * dt
        f0, fc = self.flash
        self.flash = (max(0.0, f0 - 2.4 * dt), fc)
        for t in self.toasts:
            t[2] -= dt
        self.toasts = [t for t in self.toasts if t[2] > 0]
        for o in self.obs:
            o.reveal = max(0.0, getattr(o, "reveal", 0.0) - dt) if o.kind != "shard" else 0.0
            if o.kind == "gate":
                o.flash = max(0.0, o.flash - 1.8 * dt)
            if o.kind != "shard" and self.pulse_t < 1.3 and self.s <= o.s <= self.wave_s:
                o.reveal = 2.2
        # trail sparks + dust
        if m != "over":
            hc = rgb(self.hue, 0.8, 1.0)
            self.particles.emit(world_pos(self.s - 0.6, self.u, self.v), 2, 2.2, hc, (0.4, 0.9),
                                bias=(0, 0, self.speed * 0.55))
        self.particles.update(dt)

        if m in ("play", "title"):
            self.interactions(dt)
        elif m == "over":
            self.over_t += dt

    def interactions(self, dt):
        s0, s1, u, v = self.prev_s, self.s, self.u, self.v
        playing = self.mode == "play"
        # energy = light.  drains steadily; in attract mode it is topped up
        if playing:
            self.energy -= (1.5 + 1.0 * min(1.0, self.s / 5000.0)) * dt
        else:
            self.energy = max(self.energy, 55.0)
        for o in self.obs:
            if o.s < s0 - 3 or o.s > s1 + 6:
                continue
            if o.kind == "shard":
                if not o.taken and s0 - 0.9 <= o.s <= s1 + 0.9 and math.hypot(u - o.u, v - o.v) < 1.75:
                    o.taken = True
                    res = gx.hue_distance(o.hue, self.hue) <= HUE_TOL
                    self.chain_up(res)
                    gain = 7.0 + (6.0 if res else 0.0)
                    self.energy = min(100.0, self.energy + gain)
                    self.score += (60 if res else 25) * max(1, self.chain // 2 + 1)
                    self.shards_got += 1
                    self.buzz(0.12, 50)
                    self.audio.play(f"shard{min(7, self.chain % 8)}", 0.55)
                    self.particles.emit(world_pos(o.s, o.u, o.v), 26, 9.0, rgb(o.hue, 0.7, 1.0))
                    o.s = -1e9
            elif o.kind == "gate":
                if o.state == "armed" and s0 <= o.s <= s1:
                    if gx.hue_distance(o.hue, self.hue) <= HUE_TOL:
                        o.state, o.flash = "passed", 1.0
                        self.gates_ok += 1
                        self.chain += 3
                        self.score += 300 * max(1, self.chain // 3)
                        self.energy = min(100.0, self.energy + 18.0)
                        self.toast(f"GATE MATCH   x{max(1, self.chain // 3)}", rgb(o.hue, 0.6, 1.0))
                        self.audio.play("gate_ok", 0.7)
                        self.particles.emit(world_pos(o.s, u, v), 90, 14.0, rgb(o.hue, 0.7, 1.0), (0.6, 1.5))
                        self.flash = (0.35, rgb(o.hue, 0.6, 1.0))
                        self.buzz(0.4, 140)
                    elif playing:
                        o.state, o.flash = "failed", 1.0
                        self.damage(30.0, "HUE MISMATCH", rgb(o.hue), world_pos(o.s, u, v), "gate_fail")
            elif o.kind == "pillar":
                if self.invuln <= 0 and playing and o.hit(s0, s1, u, v):
                    self.damage(22.0, "HULL IMPACT", HAZARD, world_pos(o.s, u, v), "crash")
            elif o.kind == "wheel":
                if self.invuln <= 0 and playing and o.hit(s0, s1, u, v, self.time):
                    self.damage(22.0, "HULL IMPACT", HAZARD, world_pos(o.s, u, v), "crash")
        if playing and self.energy <= 0.0:
            self.game_over()

    def chain_up(self, resonance):
        self.chain = self.chain + 1 if resonance or self.chain < 3 else max(0, self.chain - 1)
        if resonance:
            self.toast("RESONANCE", rgb(self.hue, 0.5, 1.0), 0.7)

    def damage(self, amount, label, col, pos, sound):
        self.energy -= amount
        self.slow = 0.55
        self.invuln = 1.2
        self.shake = 1.0
        self.chain = 0
        self.flash = (0.55, col)
        self.toast(label, col)
        self.audio.play(sound, 0.9)
        self.particles.emit(pos, 120, 16.0, col, (0.5, 1.4))
        self.buzz(0.9, 280)

    def buzz(self, strength, ms):
        if self.settings["rumble"] and not self.attract:
            self.gamepad.rumble(strength, ms)

    def game_over(self):
        self.buzz(1.0, 600)
        self.mode = "over"
        self.menu_over.reset_focus()
        self.over_t = 0.0
        self.audio.play("over", 0.8)
        self.particles.emit(world_pos(self.s, self.u, self.v), 260, 20.0, rgb(self.hue, 0.7, 1.0), (0.8, 2.2))
        if self.score > self.best:
            self.best, self.new_best = self.score, True
            try:
                with open(SAVE_PATH, "w") as fh:
                    json.dump({"best": int(self.best)}, fh)
            except OSError:
                pass

    def _load_best(self):
        try:
            with open(SAVE_PATH) as fh:
                return float(json.load(fh).get("best", 0))
        except Exception:
            return 0.0

    def fire_pulse(self):
        if self.mode == "play" and self.pulse_cd <= 0 and self.energy > 12:
            self.energy -= 8.0
            self.pulse_cd = 3.5
            self.pulse_t = 0.0
            self.wave_s = self.s
            self.light_boost = 1.0
            self.audio.play("pulse", 0.8)

    # ------------------------------------------------------------ camera
    def camera(self):
        sn = gx.clamp01((self.speed - 20) / 40.0)
        slope = float((path_x(self.s + 6) - path_x(self.s)) / 6.0)
        slope2 = float((path_x(self.s + 12) - path_x(self.s + 6)) / 6.0)
        curv = (slope2 - slope) / 6.0
        roll = max(-14.0, min(14.0, self.vu * 0.55 + curv * 900.0))
        modes = [(1.0, 8.5, 18.0), (0.6, 5.0, 16.0), (0.0, 0.8, 22.0)]
        cvh, behind, ahead = modes[self.cam_mode]
        side = 0.0
        if self.ortho_cam:                          # parallel projection looks degenerate straight down the axis:
            cvh, behind, ahead, side = 2.2, 16.0, 6.0, 2.6   # view it obliquely so the lack of convergence is visible
        play = np.array([self.u * 0.55 + side, self.v * 0.55 + cvh, behind, ahead,
                         self.settings["fov"] - 2.0 + 16.0 * sn + 7.0 * max(0.0, 1.0 - self.pulse_t * 2.2), roll])
        if self.mode == "title":
            cam = self.title_cam.at(self.time)
            cam = np.array([self.u * 0.4 + cam[0], self.v * 0.4 + cam[1], cam[2], cam[3], cam[4], cam[5] + roll * 0.4])
        elif self.mode == "over":
            tgt = np.array([self.u * 0.3, self.v * 0.3 + 2.2, 16.0, 12.0, 62.0, 0.0])
            cam = gx.lerp(play, tgt, gx.smoothstep(self.over_t / 1.6))
        elif self.mode == "countdown":
            cam0 = self.title_cam.at(self.time)
            cam0 = np.array([self.u * 0.4 + cam0[0], self.v * 0.4 + cam0[1], cam0[2], cam0[3], cam0[4], cam0[5]])
            cam = gx.lerp(cam0, play, gx.smoothstep(1.0 - self.countdown / 2.2))
        else:
            cam = play
        sc = self.s - cam[2]
        self.cull_s = sc + 4.5          # anything this close to the lens is not drawn (hazards would flash through the camera)
        sh = self.shake * 0.35 if self.settings["motion_fx"] else 0.0
        eye = np.array([float(path_x(sc)) + cam[0] + sh * np.random.randn(), float(path_y(sc)) + cam[1] + sh * np.random.randn(), -sc])
        tgt = np.array(world_pos(self.s + cam[3], self.u * 0.35, self.v * 0.35))
        r = math.radians(cam[5])
        up = (math.sin(r), math.cos(r), 0.0)
        return eye, tgt, up, float(cam[4])

    # ------------------------------------------------------------ rendering
    def set_mat(self, diffuse, emission=(0, 0, 0), spec=0.5, shin=40.0):
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, (diffuse[0] * 0.5, diffuse[1] * 0.5, diffuse[2] * 0.5, 1))
        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, (*diffuse, 1))
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, (spec, spec, spec, 1))
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, shin)
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, (*emission, 1))

    def light_params(self):
        ef = max(0.0, self.energy) / 100.0
        gain = 0.7 + 1.5 * ef ** 0.7 + 1.6 * self.light_boost
        kq = 0.0125 + (1.0 - ef) * 0.04 - 0.008 * self.light_boost
        return gain, max(0.004, kq)

    # ---- Premium shader hooks (no-ops in Classic mode, so the fixed-function path is untouched)
    def fx_lit(self, **kw):
        if self.fx:
            self.fx.use_lit(fog=self.fog_density, **kw)

    def fx_glow(self, gain=1.0, tex=False):
        if self.fx:
            self.fx.use_glow(gain=gain, tex=tex, fog=self.fog_density)

    def fx_off(self):
        if self.fx:
            self.fx.off()

    def setup_lights(self):
        gain, kq = self.light_params()
        zr = rgb(float(zone_hue(self.s + 80)), 0.8, 1.0)
        hc = mixc((1, 1, 1), rgb(self.hue), 0.78)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_LIGHT1)
        pos = world_pos(self.s + 1.5, self.u, self.v)
        glLightfv(GL_LIGHT0, GL_POSITION, (*pos, 1.0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (0, 0, 0, 1))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (hc[0] * gain, hc[1] * gain, hc[2] * gain, 1))
        glLightfv(GL_LIGHT0, GL_SPECULAR, (hc[0] * gain, hc[1] * gain, hc[2] * gain, 1))
        glLightf(GL_LIGHT0, GL_CONSTANT_ATTENUATION, 1.0)
        glLightf(GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.05)
        glLightf(GL_LIGHT0, GL_QUADRATIC_ATTENUATION, kq)
        far = world_pos(self.s + 85.0, 0, 0)                 # faint coloured glow at the end of the tunnel
        glLightfv(GL_LIGHT1, GL_POSITION, (*far, 1.0))
        glLightfv(GL_LIGHT1, GL_AMBIENT, (0, 0, 0, 1))
        glLightfv(GL_LIGHT1, GL_DIFFUSE, (zr[0] * 1.5, zr[1] * 1.5, zr[2] * 1.5, 1))
        glLightfv(GL_LIGHT1, GL_SPECULAR, (0, 0, 0, 1))
        glLightf(GL_LIGHT1, GL_CONSTANT_ATTENUATION, 1.0)
        glLightf(GL_LIGHT1, GL_LINEAR_ATTENUATION, 0.0)
        glLightf(GL_LIGHT1, GL_QUADRATIC_ATTENUATION, 0.004)

    def draw_tunnel(self, beat):
        k0 = int(math.floor((self.s - 14.0) / RING_DS))
        kk = k0 + np.arange(NR)
        s_arr = kk * RING_DS
        cx, cy, R = path_x(s_arr), path_y(s_arr), tunnel_r(s_arr)
        X = cx[:, None] + R[:, None] * COS[None, :]
        Y = cy[:, None] + R[:, None] * SIN[None, :]
        Z = np.broadcast_to(-s_arr[:, None], X.shape)
        V = np.ascontiguousarray(np.stack([X, Y, Z], axis=-1).reshape(-1, 3), np.float32)
        zc = gx.hsv_to_rgb_np(zone_hue(s_arr), 0.55, 1.0)                      # (NR,3)
        panel = 0.80 + 0.20 * (((kk[:, None] // 2) + np.arange(NSEG)[None, :]) % 2)
        rib = np.where(kk % 4 == 0, 0.5, 1.0)[:, None]
        base = (0.55 * np.array([0.62, 0.64, 0.70]) + 0.45 * zc * 0.8)[:, None, :]
        C = np.ascontiguousarray((base * (panel * rib)[:, :, None]).reshape(-1, 3), np.float32)

        glEnable(GL_LIGHTING)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, (0.55, 0.55, 0.6, 1))
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 22.0)
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, (0, 0, 0, 1))
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.5, 1.5)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        glVertexPointer(3, GL_FLOAT, 0, V)
        glNormalPointer(GL_FLOAT, 0, self.t_norm)
        glColorPointer(3, GL_FLOAT, 0, C)
        self.fx_lit(bump=True, vcol=True, lights=(1, 1, 0))          # Premium: per-pixel Phong + ribbed normal map
        glDrawElements(GL_TRIANGLES, len(self.t_idx), GL_UNSIGNED_INT, self.t_idx)
        self.fx_off()
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisable(GL_COLOR_MATERIAL)
        glDisable(GL_LIGHTING)

        # glowing grid (additive, unlit): rings + longitudinal veins, pulsing with the music
        pulse = 0.35 + 0.65 * math.exp(-4.0 * beat)
        gc = gx.hsv_to_rgb_np(zone_hue(s_arr), 0.85, 1.0) * (0.55 * pulse + 0.18)
        G = np.ascontiguousarray(np.concatenate([np.repeat(gc[:, None, :], NSEG, axis=1).reshape(-1, 3),
                                                 np.ones((NR * NSEG, 1))], axis=1), np.float32)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glColorPointer(4, GL_FLOAT, 0, G)
        self.fx_glow(gain=2.1)                                         # HDR gain feeds the bloom
        glLineWidth(max(1.0, 1.6 * self.ps3))
        glDrawElements(GL_LINES, len(self.t_ring[k0 % 2]), GL_UNSIGNED_INT, self.t_ring[k0 % 2])
        glLineWidth(max(1.0, 1.0 * self.ps3))
        glDrawElements(GL_LINES, len(self.t_long), GL_UNSIGNED_INT, self.t_long)
        self.fx_off()
        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)

    def draw_cube(self, pos, ang_deg, off, scl):
        glPushMatrix()
        glTranslatef(*pos)
        glRotatef(ang_deg, 0, 0, 1)
        glTranslatef(*off)
        glScalef(*scl)
        glCallList(self.lists["cube"])
        glPopMatrix()

    def draw_cube_edges(self, pos, ang_deg, off, scl):
        glPushMatrix()
        glTranslatef(*pos)
        glRotatef(ang_deg, 0, 0, 1)
        glTranslatef(*off)
        glScalef(*scl)
        glCallList(self.lists["edges"])
        glPopMatrix()

    def draw_solids(self):
        """Opaque, lit objects: pillars, spoke wheels, shards and the player's orb."""
        glEnable(GL_LIGHTING)
        self.fx_lit(lights=(1, 1, 0), rim=0.0)
        for o in self.obs:
            if o.s < self.cull_s or o.s > self.s + 230:
                continue
            c = (float(path_x(o.s)), float(path_y(o.s)), -o.s)
            R = float(tunnel_r(o.s))
            if o.kind == "pillar":
                self.set_mat((0.34, 0.28, 0.36), (0.09 + 0.12 * min(1, o.reveal), 0.015, 0.01), 0.8, 60)
                self.draw_cube(c, math.degrees(o.ang), (R - o.length / 2 + 0.25, 0, 0), (o.length + 0.5, o.width, o.depth))
            elif o.kind == "wheel":
                self.set_mat((0.22, 0.18, 0.2), (0.10 + 0.12 * min(1, o.reveal), 0.02, 0.01), 0.8, 60)
                for a in o.angles(self.time):
                    self.draw_cube(c, math.degrees(a), (R / 2, 0, 0), (R, o.thick, o.depth))
                glPushMatrix()
                glTranslatef(*c)
                glScalef(0.95, 0.95, 0.95)
                glCallList(self.lists["sphere"])
                glPopMatrix()
            elif o.kind == "shard" and not o.taken:
                col = rgb(o.hue, 0.75, 1.0)
                self.set_mat(tuple(x * 0.4 for x in col), tuple(x * 0.85 for x in col), 0.9, 80)
                p = world_pos(o.s, o.u, o.v)
                glPushMatrix()
                glTranslatef(p[0], p[1] + 0.12 * math.sin(self.time * 3 + o.s), p[2])
                glRotatef(self.time * 90 + o.s * 20, 0, 1, 0)
                glRotatef(25, 1, 0, 0)
                glScalef(0.4, 0.62, 0.4)
                glCallList(self.lists["octa"])
                glPopMatrix()
        # the orb itself: a glowing, specular sphere lit by its own camera-fixed key light
        if (self.mode != "over" or self.over_t < 0.15) and self.cam_mode != 2:      # no orb in cockpit view
            blink = self.invuln > 0 and int(self.time * 18) % 2 == 0
            if not blink:
                hc = rgb(self.hue, 0.85, 1.0)
                glDisable(GL_LIGHT0)
                glDisable(GL_LIGHT1)
                glEnable(GL_LIGHT2)
                glPushMatrix()
                glLoadIdentity()                                        # identity => light fixed in EYE space
                glLightfv(GL_LIGHT2, GL_POSITION, (-0.5, 0.8, 1.0, 0.0))
                glPopMatrix()
                glLightfv(GL_LIGHT2, GL_DIFFUSE, (1.0, 1.0, 1.0, 1))
                glLightfv(GL_LIGHT2, GL_SPECULAR, (1.0, 1.0, 1.0, 1))
                glLightfv(GL_LIGHT2, GL_AMBIENT, (0.25, 0.25, 0.25, 1))
                self.set_mat(mixc(hc, (1, 1, 1), 0.25), tuple(x * 0.75 for x in hc), 1.0, 70)
                self.fx_lit(lights=(0, 0, 1), rim=0.9, rim_col=mixc(hc, (1, 1, 1), 0.3))
                p = world_pos(self.s, self.u, self.v)
                glPushMatrix()
                glTranslatef(*p)
                glScalef(ORB_R, ORB_R, ORB_R)
                glCallList(self.lists["sphere"])
                glPopMatrix()
                glDisable(GL_LIGHT2)
                glEnable(GL_LIGHT0)
                glEnable(GL_LIGHT1)
        self.fx_off()
        glDisable(GL_LIGHTING)

    def billboard(self, p, size, col, a, V):
        """Camera-facing additive glow sprite at world point p."""
        glPushMatrix()
        glTranslatef(*p)
        B = np.eye(4)
        B[:3, :3] = V[:3, :3].T
        glMultMatrixf(gx.gl_matrix(B))
        glScalef(size, size, 1)
        glColor4f(col[0], col[1], col[2], a)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(-1, -1)
        glTexCoord2f(1, 0); glVertex2f(1, -1)
        glTexCoord2f(1, 1); glVertex2f(1, 1)
        glTexCoord2f(0, 1); glVertex2f(-1, 1)
        glEnd()
        glPopMatrix()

    def draw_points(self, pos, rgba, px, gain):
        """Glowing dots.  Classic: GL_POINTS.  Premium: camera-facing soft quads through the HDR glow shader
        (smoothed GL_POINTS into a float framebuffer is unreliable across drivers)."""
        pos = np.ascontiguousarray(pos, np.float32)
        rgba = np.ascontiguousarray(rgba, np.float32)
        n = len(pos)
        if n == 0:
            return
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_COLOR_ARRAY)
        if not self.fx:
            glPointSize(max(1.0, px * self.ps3))
            glVertexPointer(3, GL_FLOAT, 0, pos)
            glColorPointer(4, GL_FLOAT, 0, rgba)
            glDrawArrays(GL_POINTS, 0, n)
            glDisableClientState(GL_COLOR_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)
            return
        V, Pm = self.view_proj
        right, up = V[0, :3], V[1, :3]
        eye = -(V[:3, :3].T @ V[:3, 3])
        d = np.linalg.norm(pos - eye, axis=1)
        hpx = float(self.fx.sh)
        if self.ortho_cam:
            wpp = np.full(n, 2.0 / (abs(float(Pm[1, 1])) * hpx))
        else:
            wpp = 2.0 * d / (abs(float(Pm[1, 1])) * hpx)
        half = (0.5 * px * self.ps3 * 1.7 * wpp / np.sqrt(1.0 + 0.0016 * d * d)).astype(np.float32)[:, None, None]
        corners = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], np.float32)
        quad = (pos[:, None, :] + half * (corners[None, :, 0:1] * right[None, None, :] + corners[None, :, 1:2] * up[None, None, :]))
        verts = np.ascontiguousarray(quad.reshape(-1, 3), np.float32)
        cols = np.ascontiguousarray(np.repeat(rgba[:, None, :], 4, axis=1).reshape(-1, 4), np.float32)
        tc = np.ascontiguousarray(np.tile((corners * 0.5 + 0.5).astype(np.float32), (n, 1)))
        self.fx_glow(gain=gain, tex=True)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.glow_tex)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glVertexPointer(3, GL_FLOAT, 0, verts)
        glColorPointer(4, GL_FLOAT, 0, cols)
        glTexCoordPointer(2, GL_FLOAT, 0, tc)
        glDrawArrays(GL_QUADS, 0, 4 * n)
        glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisable(GL_TEXTURE_2D)
        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        self.fx_off()

    def draw_glow(self, V, beat):
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        self.fx_glow(gain=2.2)
        glLineWidth(max(1.0, 2.0 * self.ps3))
        for o in self.obs:
            if o.s < self.cull_s or o.s > self.s + 230:
                continue
            c = (float(path_x(o.s)), float(path_y(o.s)), -o.s)
            R = float(tunnel_r(o.s))
            if o.kind == "pillar":
                a = 0.45 + 0.55 * min(1.0, o.reveal) + 0.15 * beat
                glColor4f(*HAZARD, a)
                self.draw_cube_edges(c, math.degrees(o.ang), (R - o.length / 2 + 0.25, 0, 0), (o.length + 0.5, o.width, o.depth))
            elif o.kind == "wheel":
                a = 0.5 + 0.5 * min(1.0, o.reveal)
                glColor4f(*HAZARD, a)
                for ang in o.angles(self.time):
                    self.draw_cube_edges(c, math.degrees(ang), (R / 2, 0, 0), (R, o.thick, o.depth))
                glPushMatrix(); glTranslatef(*c); glScalef(R, R, 1); glColor4f(*HAZARD, 0.35 + 0.4 * min(1, o.reveal))
                glCallList(self.lists["ring"]); glPopMatrix()
            elif o.kind == "gate":
                col = rgb(o.hue)
                glPushMatrix(); glTranslatef(*c)
                for k, (rs, w) in enumerate(((0.98, 3.5), (0.93, 1.5), (0.86, 1.0))):
                    glLineWidth(max(1.0, w * self.ps3))
                    glPushMatrix(); glScalef(R * rs, R * rs, 1)
                    glColor4f(*col, (0.9 if o.state == "armed" else 0.35) + 0.5 * o.flash)
                    glCallList(self.lists["ring"]); glPopMatrix()
                glPopMatrix()
        # glow sprites
        self.fx_glow(gain=1.9, tex=True)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.glow_tex)
        for o in self.obs:
            if o.s < self.cull_s or o.s > self.s + 230:
                continue
            if o.kind == "shard" and not o.taken:
                self.billboard(world_pos(o.s, o.u, o.v), 1.7, rgb(o.hue, 0.8, 1.0), 0.65, V)
            elif o.kind == "gate" and o.state == "armed":
                p = (float(path_x(o.s)), float(path_y(o.s)), -o.s)
                self.billboard(p, float(tunnel_r(o.s)) * 1.05, rgb(o.hue), 0.18 + 0.12 * math.sin(self.time * 4), V)
        if (self.mode != "over" or self.over_t < 0.15) and self.cam_mode != 2:
            hc = rgb(self.hue, 0.85, 1.0)
            p = world_pos(self.s, self.u, self.v)
            k = 1.0 + 0.12 * math.sin(self.time * 9)
            self.billboard(p, 1.9 * k, hc, 0.45, V)
            self.billboard(p, 6.5 * k, hc, 0.22, V)
        glDisable(GL_TEXTURE_2D)
        self.fx_glow(gain=2.0)
        # trail ribbon
        tl = [(ts, tp) for ts, tp in self.trail if ts > self.s - 6.5]          # stop before the chase camera
        if len(tl) > 2:
            tr = np.array([tp for _, tp in tl], np.float32)
            n = len(tr)
            fade = np.clip((np.array([ts for ts, _ in tl]) - (self.s - 6.5)) / 6.5, 0, 1)[:, None] ** 1.3
            hc = np.array(rgb(self.hue, 0.8, 1.0))
            col = np.concatenate([np.repeat(hc[None, :], n, 0), fade * 0.8], axis=1).astype(np.float32)
            glEnableClientState(GL_VERTEX_ARRAY); glEnableClientState(GL_COLOR_ARRAY)
            glLineWidth(max(1.0, 3.0 * self.ps3))
            glVertexPointer(3, GL_FLOAT, 0, np.ascontiguousarray(tr))
            glColorPointer(4, GL_FLOAT, 0, np.ascontiguousarray(col))
            glDrawArrays(GL_LINE_STRIP, 0, n)
            glDisableClientState(GL_COLOR_ARRAY); glDisableClientState(GL_VERTEX_ARRAY)
        # sonar pulse shock-ring
        if self.pulse_t < 1.3:
            sp = self.wave_s
            glPushMatrix(); glTranslatef(float(path_x(sp)), float(path_y(sp)), -sp)
            R = float(tunnel_r(sp)) * 0.97
            glScalef(R, R, 1)
            glLineWidth(max(1.0, 4.0 * self.ps3))
            glColor4f(*mixc((1, 1, 1), rgb(self.hue), 0.5), 0.9 * (1 - self.pulse_t / 1.3))
            glCallList(self.lists["ring"]); glPopMatrix()
        self.fx_off()
        # dust motes drifting past
        L = 150.0
        rel = (self.mote_base * L - self.s) % L
        sm = self.s + rel
        rad = self.mote_rad * (tunnel_r(sm) - 0.8)
        ang = self.mote_ang + sm * 0.02
        P = np.stack([path_x(sm) + rad * np.cos(ang), path_y(sm) + rad * np.sin(ang), -sm], axis=1).astype(np.float32)
        zc = gx.hsv_to_rgb_np(zone_hue(sm), 0.35, 1.0)
        Cm = np.concatenate([zc, (0.65 * (1 - rel / L))[:, None]], axis=1).astype(np.float32)
        self.draw_points(P, Cm, 4.2, 1.6)
        self.particles.draw(self.draw_points)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)

    def draw_membranes(self):
        """Translucent spectrum-gate filters (drawn last among 3D, far to near)."""
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        gates = sorted([o for o in self.obs if o.kind == "gate" and o.state != "passed" and self.cull_s < o.s < self.s + 230],
                       key=lambda o: -o.s)
        self.fx_glow(gain=1.15)
        for o in gates:
            col = rgb(o.hue, 0.9, 1.0)
            R = float(tunnel_r(o.s)) * 0.93
            a = 0.20 + 0.10 * math.sin(self.time * 3 + o.s) + 0.45 * o.flash
            glPushMatrix()
            glTranslatef(float(path_x(o.s)), float(path_y(o.s)), -o.s)
            glScalef(R, R, 1)
            glColor4f(*col, a)
            glCallList(self.lists["disc"])
            glPopMatrix()
        self.fx_off()
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)

    # ---- HUD helpers
    def hud_begin(self):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, self.LW, LH, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_FOG)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def hud_end(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_FOG)
        glDisable(GL_BLEND)

    def points(self, xy, rgba, size=2.0):
        xy = np.ascontiguousarray(xy, np.float32)
        if len(xy) == 0:
            return
        glPointSize(max(1.0, size * self.ps))
        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointer(2, GL_FLOAT, 0, xy)
        if isinstance(rgba, np.ndarray):
            glEnableClientState(GL_COLOR_ARRAY)
            glColorPointer(4, GL_FLOAT, 0, np.ascontiguousarray(rgba, np.float32))
        else:
            glColor4f(*rgba)
        glDrawArrays(GL_POINTS, 0, len(xy))
        glDisableClientState(GL_COLOR_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)

    def poly_dda(self, pts, rgba, size=2.0):
        out = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out += gx.dda_line(x0, y0, x1, y1)
        self.points(np.array(out, np.float32), rgba, size)

    def rect(self, x, y, w, h, col, a):
        glColor4f(col[0], col[1], col[2], a)
        glRectf(x, y, x + w, y + h)

    def vignette(self, col, strength):
        if strength <= 0.01:
            return
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.vig_tex)
        glColor4f(col[0], col[1], col[2], min(1.0, strength))
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(0, LH)
        glTexCoord2f(1, 0); glVertex2f(self.LW, LH)
        glTexCoord2f(1, 1); glVertex2f(self.LW, 0)
        glTexCoord2f(0, 1); glVertex2f(0, 0)
        glEnd()
        glDisable(GL_TEXTURE_2D)

    def speed_lines(self):
        sn = gx.clamp01((self.speed - 24) / 36.0)
        if sn < 0.05:
            return
        t = self.time
        r0 = 0.42 + 0.58 * ((self.sline_ph + t * (0.9 + 1.4 * sn)) % 1.0)
        r1 = r0 + 0.03 + 0.10 * sn
        cx, cy, hw, hh = self.LW / 2, LH / 2, self.LW / 2 * 1.15, LH / 2 * 1.15
        a = np.cos(self.sline_ang)
        b = np.sin(self.sline_ang)
        P = np.empty((len(r0) * 2, 2), np.float32)
        P[0::2, 0], P[0::2, 1] = cx + a * r0 * hw, cy + b * r0 * hh
        P[1::2, 0], P[1::2, 1] = cx + a * r1 * hw, cy + b * r1 * hh
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glEnableClientState(GL_VERTEX_ARRAY)
        glColor4f(*mixc((1, 1, 1), rgb(self.hue), 0.5), 0.22 * sn)
        glLineWidth(max(1.0, 1.4 * self.ps))
        glVertexPointer(2, GL_FLOAT, 0, P)
        glDrawArrays(GL_LINES, 0, len(P))
        glDisableClientState(GL_VERTEX_ARRAY)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def project(self, p):
        """World point -> HUD (logical) coordinates, or None when behind / far outside the view."""
        V, P = self.view_proj
        c = P @ (V @ np.array([p[0], p[1], p[2], 1.0]))
        if c[3] <= 0.3:
            return None
        nx, ny = c[0] / c[3], c[1] / c[3]
        if abs(nx) > 1.15 or abs(ny) > 1.15:
            return None
        return (nx * 0.5 + 0.5) * self.LW, (0.5 - ny * 0.5) * LH, float(c[3])

    def draw_hud(self):
        T = self.text
        LW = self.LW
        hc = rgb(self.hue)
        cb = self.settings["colorblind"]
        # ---- top-left: score card
        self.glass(16, 14, 236, 150 if self.chain > 1 else 126, 24, (0.04, 0.06, 0.11, 0.40), (1, 1, 1, 0.14), 1.0, 0.8)
        T.draw("SCORE", 34, 38, 13, (0.62, 0.78, 0.95), 0.95, tracking=3, shadow=False, weight="semibold")
        T.draw(f"{int(self.score):,}", 33, 76, 44, (1, 1, 1), 1.0, shadow=False, weight="light")
        T.draw(f"{int(self.s):,} m", 34, 112, 19, (0.72, 0.82, 0.96), 0.95, shadow=False, weight="medium")
        if self.chain > 1:
            T.draw(f"CHAIN x{self.chain}", 34, 140, 19, mixc((1, 1, 1), hc, 0.6), 1.0, tracking=1, shadow=False, weight="semibold")
        # ---- top-centre: energy pill (DDA tick marks keep the syllabus line algorithm on screen)
        bx, by, bw, bh = self.bar
        e = max(0.0, min(1.0, self.energy / 100.0))
        col = mixc((1.0, 0.25, 0.2), (0.35, 1.0, 0.75), gx.smoothstep(e * 1.6))
        self.glass(bx - 104, 14, bw + 140, 58, 29, (0.04, 0.06, 0.11, 0.40), (1, 1, 1, 0.14), 1.0, 0.8)
        T.draw("LIGHT", bx - 20, by + bh / 2 + 1, 13, (0.62, 0.78, 0.95), 0.95, align="r", tracking=3, shadow=False, weight="semibold")
        self.glass(bx, by, bw, bh, bh / 2, (0, 0, 0, 0.55), (1, 1, 1, 0.10))
        if e > 0.01:
            self.glass(bx, by, max(bh, bw * e), bh, bh / 2, (*col, 1.0), (1, 1, 1, 0.25))
        self.points(self.hud["bar_ticks"], (0.6, 0.8, 1.0, 0.5), 1.3)
        if e < 0.3 and self.mode == "play":
            T.draw("LIGHT FAILING", LW / 2, by + 62, 18, (1, 0.35, 0.3), 0.5 + 0.5 * math.sin(self.time * 8), "c", 3, weight="semibold")
        # ---- bottom-left: hue wheel card
        self.glass(14, LH - 216, 344, 202, 28, (0.04, 0.06, 0.11, 0.40), (1, 1, 1, 0.14), 1.0, 0.8)
        cx, cy = self.wheel_c
        wp, wc = self.hud["wheel"]
        self.points(wp + (cx, cy), wc, 2.2)
        gates = [o for o in self.obs if o.kind == "gate" and o.state == "armed" and o.s > self.s - 1]
        tgt = min(gates, key=lambda o: o.s) if gates else None
        if tgt is not None and tgt.s - self.s > 170:
            tgt = None
        if cb:                                                            # colour-blind aid: name every wheel hue
            for h, nm in zip(SIX, SIX_NAMES):
                a_ = math.radians(h)
                T.draw(nm, cx + 78 * math.sin(a_), cy - 78 * math.cos(a_), 13, (1, 1, 1), 0.9, "c", shadow=True, weight="semibold")
        if tgt is not None:
            g = tgt.hue
            arc = [(cx + 70 * math.sin(math.radians(a)), cy - 70 * math.cos(math.radians(a)))
                   for a in np.arange(g - HUE_TOL, g + HUE_TOL + 0.1, 3.0)]
            self.poly_dda([(int(x), int(y)) for x, y in arc], (*rgb(g), 1.0), 3.0)
            dist = tgt.s - self.s
            ok = gx.hue_distance(g, self.hue) <= HUE_TOL
            gname = f"  {gx.hue_name(g).upper()}" if cb else ""
            T.draw(f"GATE {int(dist)} m{gname}", cx + 98, cy - 40, 17, rgb(g, 0.6, 1.0), 1.0, tracking=2, shadow=False, weight="semibold")
            T.draw("MATCHED" if ok else "MATCH HUE", cx + 98, cy - 16, 17, (0.4, 1, 0.7) if ok else (1, 0.8, 0.3), 1.0, tracking=2, shadow=False, weight="semibold")
        a = math.radians(self.hue)
        self.poly_dda([(int(cx), int(cy)), (int(cx + 58 * math.sin(a)), int(cy - 58 * math.cos(a)))], (1, 1, 1, 1), 2.6)
        glColor4f(*hc, 1.0)
        glBegin(GL_TRIANGLE_FAN)
        glVertex2f(cx, cy)
        for i in range(37):
            t = 2 * math.pi * i / 36
            glVertex2f(cx + 24 * math.cos(t), cy + 24 * math.sin(t))
        glEnd()
        hn = f"  {gx.hue_name(self.hue).upper()}" if cb else ""
        T.draw(f"HUE {int(self.hue):03d}{hn}", cx + 98, cy + 14, 17, (0.85, 0.92, 1.0), 0.95, tracking=2, shadow=False, weight="semibold")
        for i, h in enumerate(SIX):                                       # 1-6 snap swatches
            sx = 34 + i * 36
            self.glass(sx, LH - 40, 28, 22, 7, (*rgb(h), 0.95), (1, 1, 1, 0.25))
            T.draw(str(i + 1), sx + 14, LH - 28, 14, (0, 0, 0), 0.85, "c", shadow=False, weight="semibold")
        # ---- bottom-right: radar card (lines clipped by OUR Cohen-Sutherland)
        rx, ry, rw, rh = self.radar
        self.glass(rx - 12, ry - 12, rw + 24, rh + 24, 28, (0.04, 0.06, 0.11, 0.40), (1, 1, 1, 0.14), 1.0, 0.8)
        self.glass(rx, ry, rw, rh, 4, (0.0, 0.02, 0.06, 0.55), (0, 0, 0, 0))
        M = gx.compose(gx.t2_translate(rx + rw / 2, ry + rh - 16), gx.t2_scale(4.1, -1.35))
        ds = np.arange(0.0, 160.1, 8.0)
        cxs, rads = path_x(self.s + ds) - (path_x(self.s) + self.u), tunnel_r(self.s + ds)
        for sign, colr in ((-1, (0.4, 0.8, 1.0, 0.85)), (1, (0.4, 0.8, 1.0, 0.85)), (0, (0.4, 0.8, 1.0, 0.25))):
            P = gx.apply2(M, np.stack([cxs + sign * rads, ds], axis=1))
            seg = []
            for (xa, ya), (xb, yb) in zip(P, P[1:]):
                c = gx.cohen_sutherland(xa, ya, xb, yb, rx + 1, ry + 1, rx + rw - 1, ry + rh - 1)
                if c:
                    seg += gx.bresenham_line(int(c[0]), int(c[1]), int(c[2]), int(c[3]))
            self.points(np.array(seg, np.float32).reshape(-1, 2), colr, 1.6)
        blips, bcols = [], []
        for o in self.obs:
            d = o.s - self.s
            if not (0 <= d <= 160) or (o.kind == "shard" and o.taken):
                continue
            dx = float(path_x(o.s)) - (float(path_x(self.s)) + self.u) + (o.u if o.kind == "shard" else 0.0)
            px, py = gx.apply2(M, [(dx, d)])[0]
            if not (rx + 3 < px < rx + rw - 3):
                continue
            if o.kind == "gate":
                c, sz = (*rgb(o.hue), 1.0), 3
            elif o.kind == "shard":
                c, sz = (*rgb(o.hue, 0.6, 1.0), 0.8), 1
            else:
                c, sz = (*HAZARD, 1.0), 2
            for ddx in range(-sz, sz + 1):
                for ddy in range(-sz, sz + 1):
                    blips.append((px + ddx, py + ddy)); bcols.append(c)
        if blips:
            self.points(np.array(blips, np.float32), np.array(bcols, np.float32), 1.3)
        self.points(np.array([(rx + rw / 2 + i, ry + rh - 16 + j) for i in (-2, -1, 0, 1, 2) for j in (-2, -1, 0, 1, 2)], np.float32),
                    (*mixc((1, 1, 1), hc, 0.4), 1.0), 1.4)
        self.points(self.hud["radar_frame"], (0.75, 0.9, 1.0, 0.9), 1.6)
        T.draw("RADAR", rx + 10, ry + 15, 12, (0.6, 0.8, 1.0), 0.85, tracking=3, shadow=False, weight="semibold")
        # ---- pulse cooldown pill
        pc = 1.0 - self.pulse_cd / 3.5
        self.glass(LW / 2 - 118, LH - 58, 236, 42, 21, (0.04, 0.06, 0.11, 0.40), (1, 1, 1, 0.14), 1.0, 0.6)
        key = "A" if self.input_dev == "pad" else "SPACE"
        T.draw(f"{key}  PULSE", LW / 2, LH - 42, 14, (0.78, 0.92, 1.0) if pc >= 1 else (0.5, 0.6, 0.7), 0.95, "c", 3, shadow=False, weight="semibold")
        self.glass(LW / 2 - 80, LH - 28, 160, 5, 2.5, (0.2, 0.3, 0.4, 0.8), (0, 0, 0, 0))
        if pc > 0.01:
            self.glass(LW / 2 - 80, LH - 28, max(5.0, 160 * pc), 5, 2.5, (0.7, 0.95, 1.0, 1.0), (0, 0, 0, 0))
        # ---- colour-blind: name the gates in the world
        if cb and self.mode in ("play", "countdown"):
            near = sorted([o for o in self.obs if o.kind == "gate" and o.state == "armed" and self.cull_s < o.s < self.s + 150],
                          key=lambda o: o.s)[:2]
            for o in near:
                pr = self.project((float(path_x(o.s)), float(path_y(o.s)), -o.s))
                if pr is None:
                    continue
                px_, py_, dist = pr
                size = max(14.0, min(30.0, 520.0 / max(dist, 1.0)))
                name = gx.hue_name(o.hue).upper()
                tw = T.width(name, size, 3, "semibold")
                self.glass(px_ - tw / 2 - 14, py_ - size * 0.8, tw + 28, size * 1.6, size * 0.8, (0.03, 0.04, 0.08, 0.6), (*rgb(o.hue), 0.9))
                T.draw(name, px_, py_ + 1, size, (1, 1, 1), 1.0, "c", 3, shadow=False, weight="semibold")
        # ---- toasts
        for i, (txt, c, left, tot) in enumerate(self.toasts[-3:] if self.mode != "paused" else []):
            k = 1.0 - left / tot
            sc = 1.0 + 0.5 * (1 - gx.ease_out_back(k * 3.0)) if k < 0.33 else 1.0
            T.draw(txt, LW / 2, 200 + i * 42, 32, c, min(1.0, left * 3.0), "c", 4, sc, weight="semibold")
        if self.settings["show_fps"]:
            T.draw(f"{self.fps:3.0f} FPS   {self.settings['quality'].upper()}", LW - 24, 28, 14, (0.8, 0.9, 1.0), 0.8, "r", 1, shadow=True, weight="medium")

    def draw_lab(self):
        T = self.text
        x, y = self.LW - 340, 70
        self.glass(x - 18, y - 26, 346, 410, 22, (0.03, 0.05, 0.1, 0.5), (1, 1, 1, 0.14), 1.0, 0.8)
        r, g, b = rgb(self.hue)
        c, m, yy = gx.rgb_to_cmy(r, g, b)
        cc, mm, y2, kk = gx.rgb_to_cmyk(r, g, b)
        h, s, v = gx.rgb_to_hsv(r, g, b)
        p = np.array(world_pos(self.s, self.u, self.v))
        ang = math.atan2(self.v, self.u)
        R = float(tunnel_r(self.s))
        wall = np.array([float(path_x(self.s)) + R * math.cos(ang), float(path_y(self.s)) + R * math.sin(ang), -self.s - 4.0])
        n = np.array([-math.cos(ang), -math.sin(ang), 0.0])
        gain, kq = self.light_params()
        ph = gx.phong_terms(wall, n, p + (0, 0, 1.5), wall + (0, 0, 8), ka=0.2, kd=0.6, ks=0.55, shininess=22,
                            ambient_light=(0.03, 0.035, 0.05), light_diffuse=(gain,) * 3, light_specular=(gain,) * 3,
                            atten=(1.0, 0.05, kq))
        lines = [("LAB OVERLAY  (Tab)", (1, 1, 1)),
                 (f"fps {self.fps:5.1f}   speed {self.speed:4.1f}", (0.7, 0.85, 1)),
                 ("-- Module 3: colour models --", (1, 0.85, 0.4)),
                 (f"HSV  {h:5.1f}  {s:.2f}  {v:.2f}", (0.85, 0.95, 1)),
                 (f"RGB  {r:.2f}  {g:.2f}  {b:.2f}", (0.85, 0.95, 1)),
                 (f"CMY  {c:.2f}  {m:.2f}  {yy:.2f}", (0.85, 0.95, 1)),
                 (f"CMYK {cc:.2f} {mm:.2f} {y2:.2f} {kk:.2f}", (0.85, 0.95, 1)),
                 ("-- Phong at nearest wall point --", (1, 0.85, 0.4)),
                 ("shading: PER-PIXEL (GLSL)" if self.fx else "shading: per-vertex (Gouraud)", (0.6, 1, 0.8) if self.fx else (0.85, 0.95, 1)),
                 (f"N.L {ph['N.L']:.2f}   R.V {ph['R.V']:.2f}", (0.85, 0.95, 1)),
                 (f"ambient  {ph['ambient'].mean():.3f}", (0.85, 0.95, 1)),
                 (f"diffuse  {ph['diffuse'].mean():.3f}", (0.85, 0.95, 1)),
                 (f"specular {ph['specular'].mean():.3f}", (0.85, 0.95, 1)),
                 (f"att 1/(1+.05d+{kq:.3f}d^2) = {ph['att']:.3f}", (0.85, 0.95, 1)),
                 ("-- Module 2: projection --", (1, 0.85, 0.4)),
                 ("ORTHOGRAPHIC (parallel)" if self.ortho_cam else "PERSPECTIVE", (0.85, 0.95, 1)),
                 (f"camera mode {self.cam_mode + 1}/3   (V proj, C cam)", (0.85, 0.95, 1)),
                 ("-- Module 1/2: HUD algorithms --", (1, 0.85, 0.4)),
                 ("Bresenham: wheel, radar frame + lines", (0.85, 0.95, 1)),
                 ("DDA: ticks, needle, gate arc", (0.85, 0.95, 1)),
                 ("Cohen-Sutherland: radar clip", (0.85, 0.95, 1))]
        for i, (txt, col) in enumerate(lines):
            T.draw(txt, x, y + i * 18, 15, col, 1.0, shadow=False)

    # ---- screens
    def accent(self):
        return rgb((self.time * 25) % 360, 0.5, 1.0) if self.mode == "title" else rgb(self.hue, 0.55, 1.0)

    def hint_bar(self, items, y=None):
        """Bottom hint line, e.g. [('A','SELECT'), ('B','BACK')] - shows the right glyph names per device."""
        T, LW = self.text, self.LW
        y = LH - 30 if y is None else y
        total = 0.0
        for k, v in items:
            total += T.width(k, 14, 1, "semibold") + 22 + 10 + T.width(v, 14, 2, "medium") + 30
        x = LW / 2 - total / 2 + 15
        for k, v in items:
            w = self.chip(x, y, k)
            T.draw(v, x + w + 10, y + 1, 14, (0.7, 0.8, 0.92), 0.85, "l", 2, shadow=False, weight="medium")
            x += w + 10 + T.width(v, 14, 2, "medium") + 30

    def nav_hints(self):
        if self.input_dev == "pad":
            return [("A", "SELECT"), ("B", "BACK"), ("LB RB", "TABS")]
        return [("ARROWS", "MOVE"), ("ENTER", "SELECT"), ("ESC", "BACK")]

    def draw_title(self):
        T, LW = self.text, self.LW
        k = gx.smoothstep(min(1.0, self.time / 1.2))
        hc = self.accent()
        if self.screen:
            T.draw("BCS501  -  FUNDAMENTALS OF COMPUTER GRAPHICS  -  PyOpenGL", LW / 2, 20, 11, (0.5, 0.65, 0.8), 0.55, "c", 3, shadow=False, weight="medium")
            return
        T.draw("LUMEN", LW / 2, 118, 112, (1, 1, 1), k, "c", 20, weight="light")
        T.draw("DRIFT", LW / 2, 232, 112, hc, k, "c", 20, weight="light")
        T.draw("BE THE LIGHT.  MATCH THE SPECTRUM.  DON'T HIT THE DARK.", LW / 2, 298, 15, (0.72, 0.85, 1.0), 0.9 * k, "c", 4, weight="medium")
        if self.screen is None:
            ui.draw_menu(self, self.menu_main, LW / 2, 346, k, hc)
            if self.best > 0:
                T.draw(f"BEST  {int(self.best):,}", LW / 2, 650, 16, (0.8, 0.9, 1.0), 0.85 * k, "c", 4, weight="semibold")
            if self.gamepad.present:
                T.draw(f"CONTROLLER CONNECTED{('  -  ' + self.gamepad.name.upper()) if self.gamepad.name else ''}", LW / 2, 676, 12, (0.55, 0.9, 0.7), 0.8 * k, "c", 3, weight="medium")
            self.hint_bar(self.nav_hints()[:3])
        T.draw("BCS501  -  FUNDAMENTALS OF COMPUTER GRAPHICS  -  PyOpenGL", LW / 2, 20, 11, (0.5, 0.65, 0.8), 0.55, "c", 3, shadow=False, weight="medium")

    def draw_screen(self):
        """Overlays: settings and controls."""
        if self.screen == "settings":
            self.rect(0, 0, self.LW, LH, (0, 0, 0), 0.35)
            ui.draw_menu(self, self.menu_settings, self.LW / 2, None, 1.0, self.accent())
            self.hint_bar(self.nav_hints())
        elif self.screen == "controls":
            self.rect(0, 0, self.LW, LH, (0, 0, 0), 0.35)
            self.draw_controls()
            self.hint_bar([("ESC", "BACK")] if self.input_dev != "pad" else [("B", "BACK")])

    def draw_controls(self):
        T, LW = self.text, self.LW
        w, h = 900, 548
        x, y = LW / 2 - w / 2, (LH - h) / 2 - 10
        self.panel(x, y, w, h, 30)
        T.draw("Controls", LW / 2, y + 44, 32, (1, 1, 1), 1.0, "c", 1, weight="light")
        cols = [("KEYBOARD  &  MOUSE", x + 44, [
            ("W A S D", "steer"), ("ARROWS", "steer"), ("Q  E", "rotate hue"), ("WHEEL", "rotate hue"),
            ("1 - 6", "snap hue"), ("SPACE", "sonar pulse"), ("V", "projection"), ("C", "camera"),
            ("TAB", "lab overlay"), ("P  ESC", "pause"), ("F11", "fullscreen")]),
            ("GAMEPAD", x + 480, [
                ("L STICK", "steer"), ("R STICK", "rotate hue"), ("LT  RT", "rotate hue"), ("LB  RB", "snap hue 60"),
                ("A", "sonar pulse"), ("START", "pause"), ("B", "back")])]
        for title, cx, rows in cols:
            T.draw(title, cx, y + 98, 13, (0.62, 0.78, 0.95), 0.95, "l", 3, shadow=False, weight="semibold")
            for i, (k, v) in enumerate(rows):
                yy = y + 138 + i * 30
                w_ = self.chip(cx, yy, k)
                T.draw(v, cx + 130, yy + 1, 16, (0.86, 0.92, 1.0), 1.0, "l", 0, shadow=False, weight="medium")
        T.draw("Match the gate's colour.  Dodge everything red.  Shards feed your light.", LW / 2, y + h - 38, 16, (1, 0.85, 0.4), 1.0, "c", 1, shadow=False, weight="medium")

    def draw_pause(self):
        T, LW = self.text, self.LW
        self.rect(0, 0, LW, LH, (0, 0, 0), 0.40)
        if self.screen is None:
            T.draw("Paused", LW / 2, 190, 66, (1, 1, 1), 1.0, "c", 4, weight="light")
            ui.draw_menu(self, self.menu_pause, LW / 2, 250, 1.0, self.accent())
            self.hint_bar([("A", "SELECT"), ("START", "RESUME")] if self.input_dev == "pad" else [("ENTER", "SELECT"), ("P", "RESUME")], y=LH - 84)

    def draw_over(self):
        T, LW = self.text, self.LW
        k = gx.smoothstep((self.over_t - 0.8) / 0.8)
        if k <= 0:
            return
        self.rect(0, 0, LW, LH, (0, 0, 0), 0.45 * k)
        pw, ph = 640, 300
        x, y = LW / 2 - pw / 2, 96 + (1 - k) * 20
        self.panel(x, y, pw, ph, 32, k)
        T.draw("SIGNAL LOST", LW / 2, y + 46, 22, (1, 0.45, 0.4), k, "c", 8, shadow=False, weight="semibold")
        T.draw(f"{int(self.score):,}", LW / 2, y + 112, 82, (1, 1, 1), k, "c", 0, shadow=False, weight="light")
        T.draw("NEW BEST" if self.new_best else f"BEST  {int(self.best):,}", LW / 2, y + 168, 17,
               (1, 0.9, 0.4) if self.new_best else (0.7, 0.8, 0.92), k, "c", 4, shadow=False, weight="semibold")
        stats = [("DISTANCE", f"{int(self.s):,} m"), ("SHARDS", str(self.shards_got)), ("GATES", str(self.gates_ok))]
        for i, (lab, val) in enumerate(stats):
            cx = x + pw * (0.2 + 0.3 * i)
            T.draw(val, cx, y + 226, 30, (1, 1, 1), k, "c", 0, shadow=False, weight="light")
            T.draw(lab, cx, y + 262, 12, (0.62, 0.78, 0.95), k, "c", 3, shadow=False, weight="semibold")
        if self.over_t > 1.0:
            ui.draw_menu(self, self.menu_over, LW / 2, y + ph + 28, k, self.accent())
            self.hint_bar(self.nav_hints()[:2])

    # ---- one frame
    def render(self):
        beat = (self.clock_t * 104.0 / 60.0) % 1.0
        eye, tgt, up, fov = self.camera()
        aspect = self.size[0] / self.size[1]
        V = gx.look_at(eye, tgt, up)
        if self.ortho_cam:
            h = 9.5
            P = gx.ortho(-h * aspect, h * aspect, -h, h, 0.25, 420.0)
        else:
            P = gx.perspective(fov, aspect, 0.25, 420.0)
        fx = self.fx
        self.view_proj = (V, P)
        if fx:
            fx.begin_scene()                                 # 3D goes into the HDR framebuffer
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glLoadMatrixf(gx.gl_matrix(P))                       # OUR matrices drive the whole pipeline
        glMatrixMode(GL_MODELVIEW)
        glLoadMatrixf(gx.gl_matrix(V))
        self.view_proj = (V, P)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_FOG)
        self.fog_density = 0.0112 if not self.ortho_cam else 0.0075
        glFogf(GL_FOG_DENSITY, self.fog_density)
        self.setup_lights()
        self.draw_tunnel(beat)
        self.draw_solids()
        glDisable(GL_LIGHTING)
        self.draw_glow(V, beat)
        self.draw_membranes()
        if fx:                                               # bloom + tonemap + FXAA + speed FX -> the real screen
            st = self.settings
            sn = gx.clamp01((self.speed - 24.0) / 36.0)
            mfx = 1.0 if st["motion_fx"] else 0.0
            fx.make_backdrop()
            fx.finish(time=self.clock_t, speed=sn * mfx, bloom=st["bloom"], exposure=1.0,
                      grain=0.026 if st["film_grain"] else 0.0, aberration=mfx * (1.0 + 1.6 * self.shake),
                      radial=0.05 * sn * mfx, vignette=0.40)
        # ---- 2D overlay
        self.hud_begin()
        ef = max(0.0, self.energy) / 100.0
        danger = max(0.0, 0.3 - ef) / 0.3 * (0.5 + 0.5 * math.sin(self.time * 7)) if self.mode == "play" else 0.0
        if not fx:
            self.vignette((0.0, 0.0, 0.02), 0.55)
        if danger > 0:
            self.vignette((1.0, 0.05, 0.05), 0.6 * danger)
        if self.flash[0] > 0:
            self.vignette(self.flash[1], self.flash[0] * 1.5)
            glColor4f(*self.flash[1], self.flash[0] * 0.18)
            glRectf(0, 0, self.LW, LH)
        if self.mode in ("play", "countdown", "over", "paused") and self.settings["motion_fx"]:
            self.speed_lines()
        if self.mode == "title":
            self.draw_title()
        elif self.mode in ("play", "countdown", "paused", "over"):
            if self.mode != "over" or self.over_t < 1.4:
                self.draw_hud()
            if self.show_lab:
                self.draw_lab()
            if self.mode == "countdown":
                n = int(math.ceil(self.countdown))
                frac = self.countdown - math.floor(self.countdown) if self.countdown > 0 else 0
                txt = str(n) if n >= 1 else "GO"
                self.text.draw(txt, self.LW / 2, 300, 150, (1, 1, 1), min(1.0, frac * 3 + 0.2), "c", 0, 0.8 + 0.4 * frac, weight="light")
            if self.mode == "paused":
                self.draw_pause()
            if self.mode == "over":
                self.draw_over()
        if self.screen:
            self.draw_screen()
        if self.fade > 0.003:
            self.rect(0, 0, self.LW, LH, (0, 0, 0), min(1.0, self.fade))
        self.hud_end()

    # ------------------------------------------------------------ input
    KEY_ACTIONS = {K_UP: "up", K_w: "up", K_DOWN: "down", K_s: "down", K_LEFT: "left", K_a: "left",
                   K_RIGHT: "right", K_d: "right", K_RETURN: "confirm", K_SPACE: "confirm", K_ESCAPE: "back",
                   K_q: "prev", K_e: "next"}

    def resume(self):
        if self.mode == "paused":
            self.mode = self.prev_mode
            self.audio.play("click", 0.5)

    def pause(self):
        if self.mode in ("play", "countdown"):
            self.prev_mode = self.mode
            self.mode = "paused"
            self.menu_pause.reset_focus()

    def menu_events(self, events):
        for e in events:
            kind = e[0]
            if kind == "activate":
                self.audio.play("click")
                if e[1].action:
                    e[1].action()
            elif kind in ("move", "tab"):
                self.audio.play("click", 0.35)
            elif kind == "changed":
                self.audio.play("click", 0.3)
            elif kind == "back":
                if self.screen:
                    self.close_screen()
                elif self.mode == "paused":
                    self.resume()
                elif self.mode == "over":
                    self.to_title()

    def do_action(self, action, from_key=None):
        """One unified entry point for keyboard / gamepad actions."""
        if action == "disconnected":
            self.toast("CONTROLLER DISCONNECTED", (1, 0.8, 0.4), 2.0)
            if self.mode in ("play", "countdown"):
                self.pause()
            return
        if self.screen == "controls":
            if action in ("confirm", "back", "pause"):
                self.close_screen()
            return
        menu = self.active_menu()
        if menu is not None:
            if action == "pause" and self.mode == "paused" and not self.screen:
                self.resume()
                return
            if action == "pause":
                action = "back"
            if action == "back" and self.mode == "title" and not self.screen:
                if from_key == K_ESCAPE:
                    self.running = False
                return
            self.menu_events(menu.nav(action))
            return
        if self.mode in ("play", "countdown"):
            if action in ("confirm", "pulse"):
                self.fire_pulse()
            elif action in ("pause", "back"):
                self.pause()
            elif action in ("prev", "next") and from_key is None:        # gamepad shoulders: snap the hue +-60 degrees
                base = round(self.hue / 60.0) * 60.0
                self.hue_goal = (base + (60.0 if action == "next" else -60.0)) % 360.0
        elif self.mode == "over" and action == "back" and self.over_t > 1.0:
            self.to_title()

    def handle(self, ev):
        t = ev.type
        if t == QUIT:
            self.running = False
            return
        if t == VIDEORESIZE and not self.fullscreen:
            pygame.display.set_mode((max(480, ev.w), max(270, ev.h)), DOUBLEBUF | OPENGL | RESIZABLE)
            self.win_size = pygame.display.get_surface().get_size()
            vp = glGetIntegerv(GL_VIEWPORT)
            self.size = (int(vp[2]), int(vp[3])) if vp[2] > 0 and vp[3] > 0 else self.win_size
            self.init_gl()
            return
        # ---- gamepad
        acts = self.gamepad.feed(ev)
        if acts or t in (getattr(pygame, "CONTROLLERBUTTONDOWN", -1), getattr(pygame, "CONTROLLERAXISMOTION", -1)) and \
                (t != getattr(pygame, "CONTROLLERAXISMOTION", -1) or abs(getattr(ev, "value", 0)) > 12000):
            self.input_dev = "pad"
        for a in acts:
            self.do_action(a)
        # ---- mouse
        menu = self.active_menu()
        if t == MOUSEMOTION:
            self.mouse = self.to_hud(ev.pos)
            self.input_dev = "kbd"
            if menu is not None:
                menu.hover(*self.mouse)
                self.menu_events(menu.move_drag(*self.mouse) if ev.buttons[0] else [])
        elif t == MOUSEBUTTONDOWN and ev.button == 1:
            self.input_dev = "kbd"
            if self.screen == "controls":
                self.close_screen()
            elif menu is not None:
                self.menu_events(menu.press(*self.to_hud(ev.pos)))
        elif t == MOUSEBUTTONUP and ev.button == 1:
            if menu is not None:
                menu.release()
        elif t == MOUSEWHEEL and self.mode == "play" and not self.screen:
            self.hue = (self.hue + ev.y * 15.0) % 360.0
            self.hue_goal = None
        elif t == KEYDOWN:
            self.input_dev = "kbd"
            k = ev.key
            if k == K_F11:
                self.set_setting("fullscreen", not self.fullscreen)
            elif k == K_F12:
                self.want_shot = os.path.join(HERE, f"lumen_shot_{int(_time.time())}.png")
            elif k == K_m:
                self.audio.toggle_music()
            elif k == K_TAB:
                self.show_lab = not self.show_lab
            elif k == K_v:
                self.ortho_cam = not self.ortho_cam
            elif k == K_c:
                self.cam_mode = (self.cam_mode + 1) % 3
            elif self.mode in ("play", "countdown") and not self.screen:
                if k == K_SPACE:
                    self.fire_pulse()
                elif K_1 <= k <= K_6:
                    self.hue_goal = SIX[k - K_1]
                elif k in (K_p, K_ESCAPE):
                    self.pause()
            elif k == K_p and self.mode == "paused" and not self.screen:
                self.resume()
            elif self.mode == "over" and k == K_r and self.over_t > 1.0:
                self.start_run()
            else:
                act = self.KEY_ACTIONS.get(k)
                if act:
                    if act in ("prev", "next") and not (self.screen == "settings"):
                        return
                    self.do_action(act, from_key=k)

    def to_hud(self, pos):
        """window pixel (mouse) -> logical HUD units (accounts for HiDPI scaling)."""
        return (pos[0] * self.size[0] / self.win_size[0] / self.ps, pos[1] * self.size[1] / self.win_size[1] / self.ps)

    def to_title(self):
        self.screen = None
        self.fade = 1.0
        self.menu_main.reset_focus()
        self.mode = "title"
        self.reset_world(attract=True)
        self.time = 0.0

    def grab(self, path):
        w, h = self.size
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        glReadBuffer(GL_BACK)
        data = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
        pygame.image.save(pygame.image.fromstring(bytes(data), (w, h), "RGB", True), path)

    # ------------------------------------------------------------ main loop
    def run(self):
        clock = pygame.time.Clock()
        self.want_shot = None
        shots_left = self.args.shots
        shot_every = max(1, int(self.args.shot_every))
        while self.running:
            if self.args.fixed_dt:
                dt = self.args.fixed_dt
                clock.tick(0)
            else:
                dt = min(0.05, clock.tick(self.args.fps) / 1000.0)
            self.clock_t += dt
            self.fps += (min(240.0, 1.0 / max(dt, 1e-4)) - self.fps) * 0.05
            want_rep = bool(self.screen) or self.mode in ("title", "paused", "over")
            if want_rep != self._key_repeat:                           # held arrow keys auto-repeat in menus only
                self._key_repeat = want_rep
                pygame.key.set_repeat(380, 70) if want_rep else pygame.key.set_repeat()
            for ev in pygame.event.get():
                self.handle(ev)
            self.step(dt, pygame.key.get_pressed())
            self.render()
            if self.want_shot:
                self.grab(self.want_shot)
                print("saved", self.want_shot)
                self.want_shot = None
            if self.args.shots and self.frame % shot_every == 0 and shots_left > 0 and self.frame >= self.args.shot_start:
                os.makedirs(self.args.shotdir, exist_ok=True)
                self.grab(os.path.join(self.args.shotdir, f"frame_{self.frame:05d}.png"))
                shots_left -= 1
                if shots_left == 0 and self.args.exit_after_shots:
                    self.running = False
            pygame.display.flip()
            self.frame += 1
        self.settings.save()
        pygame.quit()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="LUMEN DRIFT - a 3D OpenGL tunnel game")
    ap.add_argument("--size", default="1280x720", help="window size, e.g. 1600x900")
    ap.add_argument("--fps", type=int, default=120, help="frame-rate cap (vsync usually decides)")
    ap.add_argument("--novsync", action="store_true")
    ap.add_argument("--mute", action="store_true", help="disable audio")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--autoplay", action="store_true", help="let the autopilot fly (used for testing/demos)")
    ap.add_argument("--fixed-dt", type=float, default=0.0, help="deterministic timestep (testing)")
    ap.add_argument("--shots", type=int, default=0, help="save N screenshots then (optionally) exit")
    ap.add_argument("--shot-every", type=int, default=60, help="frames between screenshots")
    ap.add_argument("--shot-start", type=int, default=0)
    ap.add_argument("--shotdir", default="shots")
    ap.add_argument("--exit-after-shots", action="store_true")
    ap.add_argument("--classic", action="store_true", help="force the Classic fixed-function renderer (the syllabus labs' pipeline)")
    ap.add_argument("--quality", choices=QUALITIES, help="override the saved graphics quality for this run")
    ap.add_argument("--settings", help="settings file path (default: next to the game)")
    ap.add_argument("--no-save", action="store_true", help="do not read or write the settings file (testing)")
    return ap.parse_args(argv)


def main():
    Game(parse_args()).run()


if __name__ == "__main__":
    main()
