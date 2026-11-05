"""
gamepad.py - controller support (Xbox / PlayStation / Switch Pro / most pads) on top of SDL2's game-controller API.

* All pygame events are translated into a small vocabulary of *actions*, so menus and gameplay do not care
  whether the input came from the keyboard, the mouse or a pad.
* Hot-plug aware (connect / disconnect at any time).  Without a pad everything is a harmless no-op.
* `feed(event)` and `update(dt)` are pure logic and can be driven with synthetic events (see test_gamepad.py).
"""
from __future__ import annotations

import math

import pygame

# SDL game-controller layout (identical on every supported pad)
BTN_A, BTN_B, BTN_X, BTN_Y, BTN_BACK, BTN_GUIDE, BTN_START = 0, 1, 2, 3, 4, 5, 6
BTN_LSTICK, BTN_RSTICK, BTN_LB, BTN_RB, BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT = 7, 8, 9, 10, 11, 12, 13, 14
AX_LX, AX_LY, AX_RX, AX_RY, AX_LT, AX_RT = 0, 1, 2, 3, 4, 5

BUTTON_ACTIONS = {
    BTN_A: "confirm", BTN_B: "back", BTN_START: "pause", BTN_BACK: "back",
    BTN_UP: "up", BTN_DOWN: "down", BTN_LEFT: "left", BTN_RIGHT: "right",
    BTN_LB: "prev", BTN_RB: "next", BTN_X: "pulse",
}


def _norm(v):
    """pygame builds differ: axis values are either raw int16 or already -1..1."""
    v = float(v)
    return max(-1.0, min(1.0, v / 32767.0 if abs(v) > 1.5 else v))


def radial_deadzone(x, y, dz=0.18):
    """Radial dead zone with re-scaling, so the stick ramps smoothly from 0 at the edge of the zone to 1."""
    m = math.hypot(x, y)
    if m <= dz:
        return 0.0, 0.0
    k = min(1.0, (m - dz) / (1.0 - dz)) / m
    return x * k, y * k


class Gamepad:
    NAV_THRESH = 0.6

    def __init__(self, use_hardware=True):
        self.ctrl = None
        self.name = ""
        self.axes = {i: 0.0 for i in range(6)}
        self.held = set()
        self.present = False
        self._ctl = None
        self._nav_dir = None
        self._nav_t = 0.0
        self._nav_first = True
        self.rumble_ok = False
        if use_hardware:
            try:
                from pygame._sdl2 import controller as c          # standard mapping + rumble
                c.init()
                self._ctl = c
                for i in range(c.get_count()):
                    if self._open(i):
                        break
            except Exception:
                self._ctl = None

    # ---- connection handling
    def _open(self, index):
        try:
            if not self._ctl.is_controller(index):
                return False
            self.ctrl = self._ctl.Controller(index)
            try:
                self.name = self.ctrl.name
            except Exception:
                self.name = "Controller"
            self.present = True
            self.rumble_ok = hasattr(self.ctrl, "rumble")
            return True
        except Exception:
            self.ctrl, self.present = None, False
            return False

    def _close(self):
        self.ctrl, self.present, self.name = None, False, ""
        self.axes = {i: 0.0 for i in range(6)}
        self.held.clear()
        self._nav_dir = None

    # ---- events -> actions
    def feed(self, ev):
        """Translate one pygame event. Returns a list of action names (possibly empty)."""
        t = ev.type
        C = getattr
        if t == getattr(pygame, "CONTROLLERDEVICEADDED", -1):
            if self._ctl is not None and not self.present:
                self._open(ev.device_index)
            else:
                self.present = True
            return []
        if t == getattr(pygame, "CONTROLLERDEVICEREMOVED", -1):
            self._close()
            return ["disconnected"]
        if t == getattr(pygame, "CONTROLLERBUTTONDOWN", -1):
            self.present = True
            self.held.add(ev.button)
            act = BUTTON_ACTIONS.get(ev.button)
            return [act] if act else []
        if t == getattr(pygame, "CONTROLLERBUTTONUP", -1):
            self.held.discard(ev.button)
            return []
        if t == getattr(pygame, "CONTROLLERAXISMOTION", -1):
            self.present = True
            self.axes[ev.axis] = _norm(ev.value)
            return []
        return []

    def update(self, dt):
        """Held-stick menu navigation with auto-repeat. Returns a list of actions."""
        x, y = self.axes[AX_LX], self.axes[AX_LY]
        d = None
        if abs(x) > self.NAV_THRESH or abs(y) > self.NAV_THRESH:
            d = ("right" if x > 0 else "left") if abs(x) >= abs(y) else ("down" if y > 0 else "up")
        if d is None:
            self._nav_dir, self._nav_first = None, True
            return []
        if d != self._nav_dir:
            self._nav_dir, self._nav_t, self._nav_first = d, 0.0, True
            return [d]
        self._nav_t += dt
        wait = 0.38 if self._nav_first else 0.11
        if self._nav_t >= wait:
            self._nav_t, self._nav_first = 0.0, False
            return [d]
        return []

    # ---- continuous controls (gameplay)
    def steer(self):
        """(x, y) in -1..1, y positive = up. D-pad also steers."""
        x, y = radial_deadzone(self.axes[AX_LX], self.axes[AX_LY])
        y = -y
        if BTN_LEFT in self.held:
            x -= 1.0
        if BTN_RIGHT in self.held:
            x += 1.0
        if BTN_UP in self.held:
            y += 1.0
        if BTN_DOWN in self.held:
            y -= 1.0
        return max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))

    def hue_rate(self):
        """-1..1: right stick X and the triggers rotate the hue."""
        rx, _ = radial_deadzone(self.axes[AX_RX], self.axes[AX_RY], 0.22)
        trig = (self.axes[AX_RT] - self.axes[AX_LT])
        trig = trig if abs(trig) > 0.12 else 0.0
        return max(-1.0, min(1.0, rx + trig))

    def rumble(self, strength, ms=180):
        if self.ctrl is not None and self.rumble_ok:
            try:
                s = max(0.0, min(1.0, strength))
                self.ctrl.rumble(int(0xFFFF * s * 0.7), int(0xFFFF * s), int(ms))
            except Exception:
                pass
