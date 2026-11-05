"""Tests for gamepad.py using synthetic controller events (no hardware needed) - run: python3 tests/test_gamepad.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root, so `python3 tests/x.py` works
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

import gamepad as gp

E = pygame.event.Event


def pad():
    return gp.Gamepad(use_hardware=False)


def test_button_actions():
    g = pad()
    cases = {gp.BTN_A: "confirm", gp.BTN_B: "back", gp.BTN_START: "pause", gp.BTN_UP: "up",
             gp.BTN_DOWN: "down", gp.BTN_LEFT: "left", gp.BTN_RIGHT: "right", gp.BTN_LB: "prev", gp.BTN_RB: "next"}
    for b, act in cases.items():
        assert g.feed(E(pygame.CONTROLLERBUTTONDOWN, button=b, instance_id=0)) == [act], b
    assert g.feed(E(pygame.CONTROLLERBUTTONDOWN, button=gp.BTN_GUIDE, instance_id=0)) == []
    assert g.present


def test_deadzone_and_steer():
    assert gp.radial_deadzone(0.1, 0.1) == (0.0, 0.0)
    x, y = gp.radial_deadzone(1.0, 0.0)
    assert abs(x - 1.0) < 1e-9 and y == 0.0
    x, y = gp.radial_deadzone(0.6, 0.0)
    assert 0.0 < x < 0.6                                   # re-scaled: ramps from 0 at the edge of the zone
    g = pad()
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LX, value=32767, instance_id=0))
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LY, value=-32767, instance_id=0))   # stick up = negative Y in SDL
    sx, sy = g.steer()
    assert sx > 0.65 and sy > 0.65 and abs((sx * sx + sy * sy) ** 0.5 - 1.0) < 1e-6   # up is positive; full diagonal = unit length
    g2 = pad()
    g2.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LX, value=0.5, instance_id=0))      # builds that give floats
    assert 0.2 < g2.steer()[0] < 0.5


def test_dpad_steers_and_release():
    g = pad()
    g.feed(E(pygame.CONTROLLERBUTTONDOWN, button=gp.BTN_LEFT, instance_id=0))
    assert g.steer() == (-1.0, 0.0)
    g.feed(E(pygame.CONTROLLERBUTTONUP, button=gp.BTN_LEFT, instance_id=0))
    assert g.steer() == (0.0, 0.0)


def test_hue_rate():
    g = pad()
    assert g.hue_rate() == 0.0
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_RT, value=32767, instance_id=0))
    assert g.hue_rate() > 0.95
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_RT, value=0, instance_id=0))
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LT, value=32767, instance_id=0))
    assert g.hue_rate() < -0.95
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LT, value=2000, instance_id=0))      # light touch ignored
    assert g.hue_rate() == 0.0


def test_stick_menu_navigation_repeats():
    g = pad()
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LY, value=32767, instance_id=0))     # stick down
    assert g.update(0.016) == ["down"]                       # immediate
    assert g.update(0.1) == []                               # initial delay
    assert g.update(0.3) == ["down"]                         # first repeat after ~0.38 s
    assert g.update(0.05) == []
    assert g.update(0.07) == ["down"]                        # fast repeat afterwards
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LY, value=0, instance_id=0))
    assert g.update(0.5) == []
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LX, value=-32767, instance_id=0))
    assert g.update(0.016) == ["left"]


def test_disconnect_resets_everything():
    g = pad()
    g.feed(E(pygame.CONTROLLERBUTTONDOWN, button=gp.BTN_RIGHT, instance_id=0))
    g.feed(E(pygame.CONTROLLERAXISMOTION, axis=gp.AX_LX, value=32767, instance_id=0))
    assert g.feed(E(pygame.CONTROLLERDEVICEREMOVED, instance_id=0)) == ["disconnected"]
    assert not g.present and g.steer() == (0.0, 0.0) and g.update(0.5) == []


def test_rumble_is_safe_without_hardware():
    pad().rumble(1.0, 200)                                   # must not raise


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"  ok  {name}")
    print(f"\nall {len(tests)} gamepad tests passed")
