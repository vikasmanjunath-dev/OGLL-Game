"""Tests for the pure-logic part of ui.py (menu navigation and pointer handling) - run: python3 tests/test_ui.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root, so `python3 tests/x.py` works
import ui


def mk_store():
    return {"vol": 0.5, "on": False, "q": "premium", "n": 0}


def items(st, log):
    return [
        ui.Item("slider", "Volume", lambda: st["vol"], lambda v: st.__setitem__("vol", v), lo=0, hi=1, step=0.1),
        ui.Item("toggle", "Grain", lambda: st["on"], lambda v: st.__setitem__("on", v)),
        ui.Item("gap"),
        ui.Item("choice", "Quality", lambda: st["q"], lambda v: st.__setitem__("q", v),
                choices=[("classic", "Classic"), ("premium", "Premium"), ("ultra", "Ultra")]),
        ui.Item("button", "Locked", enabled=lambda: False, action=lambda: log.append("locked")),
        ui.Item("button", "Go", action=lambda: log.append("go")),
    ]


def test_navigation_skips_gaps_and_disabled():
    st, log = mk_store(), []
    m = ui.Menu("T", items(st, log))
    seen = []
    for _ in range(5):
        seen.append(m.current().label)
        m.nav("down")
    assert seen == ["Volume", "Grain", "Quality", "Go", "Volume"], seen      # wraps; gap and disabled row skipped
    m.nav("up")
    m.nav("up")
    assert m.current().label == "Go"                                        # up from the first row wraps to the last


def test_value_changes():
    st, log = mk_store(), []
    m = ui.Menu("T", items(st, log))
    m.nav("right")
    assert abs(st["vol"] - 0.6) < 1e-9
    for _ in range(20):
        m.nav("right")
    assert st["vol"] == 1.0                                                 # clamped
    for _ in range(30):
        m.nav("left")
    assert st["vol"] == 0.0
    m.nav("down")
    assert m.nav("confirm")[0][0] == "changed" and st["on"] is True
    m.nav("left")
    assert st["on"] is False
    m.nav("down")
    m.nav("right")
    assert st["q"] == "ultra"
    m.nav("right")
    assert st["q"] == "classic"                                             # choice wraps
    m.nav("left")
    assert st["q"] == "ultra"


def test_button_activate_and_back():
    st, log = mk_store(), []
    m = ui.Menu("T", items(st, log))
    for _ in range(3):
        m.nav("down")
    ev = m.nav("confirm")
    assert ev[0][0] == "activate" and ev[0][1].label == "Go"
    ev[0][1].action()
    assert log == ["go"]
    assert m.nav("back") == [("back",)]


def test_tabs():
    st = mk_store()
    a = [ui.Item("toggle", "A1", lambda: st["on"], lambda v: st.__setitem__("on", v))]
    b = [ui.Item("slider", "B1", lambda: st["vol"], lambda v: st.__setitem__("vol", v), step=0.1),
         ui.Item("toggle", "B2", lambda: st["on"], lambda v: st.__setitem__("on", v))]
    m = ui.Menu("S", tabs=[("One", a), ("Two", b)], form=True)
    assert m.current().kind == "tabs"
    assert [r.label for r in m.rows[1:]] == ["A1"]
    assert m.nav("right") == [("tab", 1)]
    assert [r.label for r in m.rows[1:]] == ["B1", "B2"]
    m.nav("next")                                                           # shoulder button wraps
    assert m.tab == 0
    m.nav("prev")
    assert m.tab == 1


def test_pointer():
    st, log = mk_store(), []
    its = items(st, log)
    m = ui.Menu("T", its)
    for i, it in enumerate(m.rows):
        if it.kind != "gap":
            it.rect = (100, 50 * i, 400, 40)
    sl = m.rows[0]
    sl.track = (200, 200, 20)
    assert m.hover(150, 60) and m.current().label == "Grain"                # row 1 at y=50..90
    assert m.press(150, 60)[0][0] == "changed" and st["on"] is True
    ev = m.press(260, 10)                                                   # 30% along the slider track
    assert ev and abs(st["vol"] - 0.3) < 0.06
    m.move_drag(400, 10)
    assert st["vol"] == 1.0
    m.move_drag(0, 10)
    assert st["vol"] == 0.0
    m.release()
    m.move_drag(300, 10)
    assert st["vol"] == 0.0                                                 # no drag after release
    assert m.press(600, 10) == []                                           # outside every row
    assert m.press(150, 260)[0][0] == "activate"                            # 'Go' is row 5 at y=250..290
    assert m.press(150, 210) == []                                          # disabled row ignores clicks


def test_update_animates_focus():
    st, log = mk_store(), []
    m = ui.Menu("T", items(st, log))
    for _ in range(60):
        m.update(1 / 60)
    assert m.rows[0].focus.x > 0.9 and m.rows[1].focus.x < 0.1


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"  ok  {name}")
    print(f"\nall {len(tests)} ui tests passed")
