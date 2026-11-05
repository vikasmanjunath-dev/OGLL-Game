"""
ui.py - an Apple-style menu system: frosted-glass panels, pill buttons, switches and sliders with spring motion.

The model (`Menu`) is pure logic - keyboard, mouse and gamepad all arrive as the same few actions
("up", "down", "left", "right", "confirm", "back", "prev", "next") plus pointer calls - so it is unit-tested
without OpenGL (test_ui.py).  `draw_menu` is the only part that touches the GPU.
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional

from OpenGL.GL import *  # noqa: F401,F403

import gfxcore as gx

LH = 720


# =============================================================================================== model
class Item:
    """kind: button | toggle | slider | choice | tabs | gap"""

    def __init__(self, kind: str, label: str = "", get: Optional[Callable] = None, set: Optional[Callable] = None, *,
                 lo: float = 0.0, hi: float = 1.0, step: float = 0.05, choices=None, fmt: Optional[Callable] = None,
                 action: Optional[Callable] = None, enabled: Optional[Callable[[], bool]] = None, hint: str = ""):
        self.kind, self.label, self.get, self.set = kind, label, get, set
        self.lo, self.hi, self.step = lo, hi, step
        self.choices = list(choices or [])               # [(value, text)]
        self.fmt = fmt
        self.action = action
        self.enabled = enabled or (lambda: True)
        self.hint = hint
        self.rect = (0.0, 0.0, 0.0, 0.0)                 # filled in by layout (logical HUD units)
        self.track = (0.0, 0.0, 0.0)                     # slider track: x, w, y
        self.focus = gx.Spring(0.0, 6.5, 0.72)
        self.sw = gx.Spring(0.0, 6.0, 0.8)               # toggle / slider animated value
        self.bump = 0.0                                  # activation flash

    @property
    def focusable(self) -> bool:
        return self.kind != "gap" and self.enabled()

    def choice_index(self) -> int:
        v = self.get() if self.get else None
        for i, (val, _) in enumerate(self.choices):
            if val == v:
                return i
        return 0


class Menu:
    """A vertical list of items (optionally with a tab bar on top). Returns events from every input."""

    def __init__(self, title: str, items: Optional[List[Item]] = None, *, subtitle: str = "", tabs=None,
                 footer: Optional[List[Item]] = None, form: bool = False, width: float = 380):
        self.title, self.subtitle, self.form, self.width = title, subtitle, form, width
        self.tab_names = [t[0] for t in tabs] if tabs else []
        self.tab_items = [t[1] for t in tabs] if tabs else []
        self.tab = 0
        self.base_items = list(items or [])
        self.footer = list(footer or [])
        self.tabs_item = None
        if tabs:
            self.tabs_item = Item("tabs", "", get=lambda: self.tab, set=self._set_tab)
        self.sel = 0
        self.t = 0.0                                     # seconds since opened (entrance animation)
        self.drag: Optional[Item] = None
        self.reset_focus()

    # ---- structure
    def _set_tab(self, i):
        self.tab = i % len(self.tab_names)

    @property
    def rows(self) -> List[Item]:
        r = []
        if self.tabs_item is not None:
            r.append(self.tabs_item)
            r += self.tab_items[self.tab]
        r += self.base_items + self.footer
        return r

    def reset_focus(self):
        self.t = 0.0
        rows = self.rows
        self.sel = next((i for i, it in enumerate(rows) if it.focusable), 0)

    def current(self) -> Optional[Item]:
        rows = self.rows
        return rows[self.sel] if 0 <= self.sel < len(rows) else None

    def _move(self, d):
        rows = self.rows
        n = len(rows)
        i = self.sel
        for _ in range(n):
            i = (i + d) % n
            if rows[i].focusable:
                self.sel = i
                return True
        return False

    # ---- value helpers
    def adjust(self, it: Item, d: int, big: bool = False) -> bool:
        """Change a value by +-1 step. Returns True if something changed."""
        if it.kind == "slider":
            old = it.get()
            v = min(it.hi, max(it.lo, old + d * it.step * (4 if big else 1)))
            v = round(v / (it.step / 2)) * (it.step / 2)
            if abs(v - old) > 1e-9:
                it.set(v)
                return True
        elif it.kind == "toggle":
            want = d > 0
            if bool(it.get()) != want:
                it.set(want)
                return True
        elif it.kind == "choice" and it.choices:
            i = (it.choice_index() + d) % len(it.choices)
            it.set(it.choices[i][0])
            return True
        elif it.kind == "tabs":
            it.set(it.get() + d)
            self.sel = 0
            return True
        return False

    # ---- actions from keyboard / pad
    def nav(self, action: str):
        """Returns a list of events: ('activate', item) | ('changed', item) | ('tab', index) | ('back',) | ('move',)."""
        ev = []
        it = self.current()
        if action == "up":
            if self._move(-1):
                ev.append(("move",))
        elif action == "down":
            if self._move(1):
                ev.append(("move",))
        elif action in ("left", "right"):
            d = -1 if action == "left" else 1
            if it is not None and it.kind == "tabs":
                self.adjust(it, d)
                ev.append(("tab", self.tab))
            elif it is not None and it.kind in ("slider", "toggle", "choice"):
                if self.adjust(it, d):
                    ev.append(("changed", it))
        elif action in ("prev", "next") and self.tabs_item is not None:
            self.adjust(self.tabs_item, -1 if action == "prev" else 1)
            ev.append(("tab", self.tab))
        elif action == "confirm":
            if it is not None:
                if it.kind == "toggle":
                    it.set(not it.get())
                    ev.append(("changed", it))
                elif it.kind == "choice":
                    self.adjust(it, 1)
                    ev.append(("changed", it))
                elif it.kind == "button":
                    it.bump = 1.0
                    ev.append(("activate", it))
        elif action == "back":
            ev.append(("back",))
        return ev

    # ---- pointer
    def _hit(self, x, y):
        for i, it in enumerate(self.rows):
            rx, ry, rw, rh = it.rect
            if it.kind != "gap" and rw > 0 and rx <= x <= rx + rw and ry <= y <= ry + rh and it.focusable:
                return i, it
        return None, None

    def hover(self, x, y):
        i, it = self._hit(x, y)
        if it is not None:
            self.sel = i
            return True
        return False

    def _slider_from_x(self, it: Item, x):
        tx, tw, _ = it.track
        f = min(1.0, max(0.0, (x - tx) / max(tw, 1.0)))
        v = it.lo + f * (it.hi - it.lo)
        v = round(v / (it.step / 2)) * (it.step / 2)
        v = min(it.hi, max(it.lo, v))
        if abs(v - it.get()) > 1e-9:
            it.set(v)
            return True
        return False

    def press(self, x, y):
        i, it = self._hit(x, y)
        if it is None:
            return []
        self.sel = i
        rx, ry, rw, rh = it.rect
        if it.kind == "button":
            it.bump = 1.0
            return [("activate", it)]
        if it.kind == "toggle":
            it.set(not it.get())
            return [("changed", it)]
        if it.kind == "choice":
            self.adjust(it, -1 if x < rx + rw - 150 else 1)          # left of the value = previous, on it / right = next
            return [("changed", it)]
        if it.kind == "slider":
            self.drag = it
            return [("changed", it)] if self._slider_from_x(it, x) else []
        if it.kind == "tabs":
            n = len(self.tab_names)
            k = min(n - 1, max(0, int((x - rx) / (rw / n))))
            if k != self.tab:
                self.tab = k
                self.sel = 0
                return [("tab", k)]
        return []

    def move_drag(self, x, y):
        if self.drag is not None:
            return [("changed", self.drag)] if self._slider_from_x(self.drag, x) else []
        return []

    def release(self):
        self.drag = None

    # ---- per-frame animation
    def update(self, dt):
        self.t += dt
        cur = self.current()
        for it in self.rows:
            it.focus.target = 1.0 if it is cur else 0.0
            it.focus.update(dt)
            if it.kind == "toggle":
                it.sw.target = 1.0 if it.get() else 0.0
                it.sw.update(dt)
            elif it.kind == "slider":
                span = max(it.hi - it.lo, 1e-9)
                it.sw.target = (it.get() - it.lo) / span
                it.sw.update(dt)
            it.bump = max(0.0, it.bump - 4.0 * dt)


# =============================================================================================== drawing
def _fmt_value(it: Item) -> str:
    v = it.get()
    if it.fmt:
        return it.fmt(v)
    return f"{v:.2f}"


def draw_menu(g, m: Menu, x_center: float, y_top, alpha: float = 1.0, accent=(0.40, 0.78, 1.0)):
    """Lay out and draw a menu. g = Game (gives text, rounded-rect drawer, scale).  Returns nothing."""
    T = g.text
    ease = gx.ease_out_cubic(min(1.0, m.t / 0.45))
    a = alpha * ease
    dy = (1.0 - ease) * 22.0
    rows = m.rows
    hs = {"gap": 14.0, "tabs": 54.0, "button": 62.0}
    row_h, gap = 46.0, 4.0
    def height(rs):
        return sum(hs.get(r.kind, row_h + gap) for r in rs)

    if m.form:
        tallest = max([height([m.tabs_item] + t + m.base_items) for t in m.tab_items] or [height(rows)])
        foot_h = height(m.footer)
        ph = 92.0 + tallest + foot_h + 14                    # constant: the panel does not jump between tabs
    else:
        ph = sum(18.0 if r.kind == "gap" else 68.0 for r in rows) - 14
    if y_top is None:
        y_top = max(16.0, (LH - ph) / 2)
    y = y_top + dy
    if m.form:
        pw = 700.0
        px0 = x_center - pw / 2
        g.panel(px0, y, pw, ph, 28, a, shadow=1.0)
        T.draw(m.title, x_center, y + 42, 30, (1, 1, 1), a, "c", 1, weight="light")
        cy = y + 82
        foot = set(id(f) for f in m.footer)
        for it in rows:
            if id(it) in foot and cy < y + ph - 14 - height(m.footer):
                cy = y + ph - 14 - height(m.footer)           # pin the footer to the bottom of the panel
                foot.clear()
            if it.kind == "gap":
                it.rect = (0, 0, 0, 0)
                cy += hs["gap"]
            elif it.kind == "tabs":
                it.rect = (px0 + 40, cy, pw - 80, 40.0)
                _draw_tabs(g, m, it, a, accent)
                cy += hs["tabs"]
            elif it.kind == "button":
                it.rect = (x_center - 130, cy + 4, 260, 48.0)
                _draw_button(g, it, a, accent)
                cy += hs["button"]
            else:
                it.rect = (px0 + 28, cy, pw - 56, row_h)
                _draw_row(g, it, a, accent)
                cy += row_h + gap
    else:
        w, h, gap = m.width, 54.0, 14.0
        for it in rows:
            if it.kind == "gap":
                it.rect = (0, 0, 0, 0)
                y += 18
                continue
            it.rect = (x_center - w / 2, y, w, h)
            _draw_button(g, it, a, accent)
            y += h + gap


def _draw_button(g, it: Item, a, accent):
    x, y, w, h = it.rect
    f = it.focus.x
    f = max(0.0, min(1.0, f))
    grow = 5.0 * f + 3.0 * it.bump
    ok = it.enabled()
    x2, y2, w2, h2 = x - grow, y - grow * 0.5, w + 2 * grow, h + grow
    acc = (1.0, 0.42, 0.40) if it.hint == "danger" else accent
    fill = (acc[0] * 0.32 * f + 0.07 * (1 - f), acc[1] * 0.32 * f + 0.09 * (1 - f), acc[2] * 0.32 * f + 0.14 * (1 - f),
            (0.38 + 0.2 * f) if g.fx else (0.55 + 0.25 * f))
    border = (*(acc if f > 0.5 or it.hint == "danger" else (1, 1, 1)), (0.18 + 0.7 * f + (0.25 if it.hint == "danger" else 0)) * a)
    g.glass(x2, y2, w2, h2, h2 / 2, fill, border, a, shadow=0.7 * f)
    col = (1, 1, 1) if ok else (0.55, 0.6, 0.68)
    g.text.draw(it.label, x + w / 2, y + h / 2 + 1, 21, col, a * (0.82 + 0.18 * f), "c", 3, shadow=False, weight="semibold")


def _draw_tabs(g, m: Menu, it: Item, a, accent):
    x, y, w, h = it.rect
    f = it.focus.x
    g.glass(x, y, w, h, h / 2, (0.05, 0.07, 0.12, 0.45 if g.fx else 0.7), (1, 1, 1, 0.12 * a), a)
    n = len(m.tab_names)
    sw = w / n
    knob = x + sw * m.tab
    g.glass(knob + 3, y + 3, sw - 6, h - 6, (h - 6) / 2, (accent[0] * 0.55, accent[1] * 0.55, accent[2] * 0.55, 0.85),
            (1, 1, 1, (0.18 + 0.5 * f) * a), a)
    for i, name in enumerate(m.tab_names):
        act = i == m.tab
        g.text.draw(name, knob - sw * m.tab + sw * i + sw / 2, y + h / 2 + 1, 17, (1, 1, 1) if act else (0.7, 0.78, 0.9),
                    a, "c", 2, shadow=False, weight="semibold")


def _draw_row(g, it: Item, a, accent):
    x, y, w, h = it.rect
    f = max(0.0, min(1.0, it.focus.x))
    if f > 0.01:
        g.glass(x, y, w, h, 16, (accent[0], accent[1], accent[2], 0.13 * f), (*accent, 0.55 * f * a), a)
    g.text.draw(it.label, x + 20, y + h / 2 + 1, 19, (1, 1, 1) if it.enabled() else (0.5, 0.55, 0.62), a,
                "l", 0, shadow=False, weight="medium")
    cx = x + w - 20          # right edge of the control
    if it.kind == "toggle":
        tw, th = 54.0, 30.0
        k = max(0.0, min(1.0, it.sw.x))
        tx, ty = cx - tw, y + (h - th) / 2
        off, on = (0.28, 0.31, 0.38), (accent[0] * 0.85, accent[1] * 0.85 + 0.1, accent[2] * 0.85)
        col = tuple(off[i] * (1 - k) + on[i] * k for i in range(3))
        g.glass(tx, ty, tw, th, th / 2, (*col, 1.0), (1, 1, 1, 0.18 * a), a)
        kx = tx + 3 + (tw - th) * k
        g.glass(kx, ty + 3, th - 6, th - 6, (th - 6) / 2, (1, 1, 1, 1.0), (0, 0, 0, 0.0), a, shadow=0.5)
    elif it.kind == "slider":
        tw = 216.0
        tx, ty = cx - tw - 84, y + h / 2
        it.track = (tx, tw, ty)
        k = max(0.0, min(1.0, it.sw.x))
        g.glass(tx, ty - 3, tw, 6, 3, (0.25, 0.3, 0.4, 0.9), (0, 0, 0, 0), a)
        if k > 0.001:
            g.glass(tx, ty - 3, max(6.0, tw * k), 6, 3, (*accent, 1.0), (0, 0, 0, 0), a)
        g.glass(tx + tw * k - 11, ty - 11, 22, 22, 11, (1, 1, 1, 1.0), (0, 0, 0, 0.0), a, shadow=0.6)
        g.text.draw(_fmt_value(it), cx, y + h / 2 + 1, 17, (0.78, 0.86, 1.0), a, "r", 0, shadow=False, weight="medium")
    elif it.kind == "choice":
        txt = it.choices[it.choice_index()][1] if it.choices else ""
        arrow = (0.5 + 0.5 * f)
        g.text.draw(txt, cx - 24, y + h / 2 + 1, 19, (0.86, 0.93, 1.0), a, "r", 0, shadow=False, weight="semibold")
        g.text.draw(">", cx, y + h / 2 + 1, 19, (0.8, 0.9, 1.0), a * arrow, "r", 0, shadow=False, weight="semibold")
        wtxt = g.text.width(txt, 19, 0, "semibold")
        g.text.draw("<", cx - 24 - wtxt - 14, y + h / 2 + 1, 19, (0.8, 0.9, 1.0), a * arrow, "r", 0, shadow=False, weight="semibold")
