"""Tests for settings.py - run:  python3 tests/test_settings.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root, so `python3 tests/x.py` works
import json
import os
import tempfile

import settings as st


def _tmp():
    d = tempfile.mkdtemp()
    return os.path.join(d, "s.json")


def test_defaults_are_valid():
    for k, v in st.DEFAULTS.items():
        assert st.sanitize(k, v) == v, k
    assert st.DEFAULTS["quality"] in st.QUALITIES
    for q in st.QUALITIES:
        assert set(st.QUALITY_PROFILES[q]) == {"premium", "scale", "bloom_levels", "msaa"}


def test_roundtrip():
    p = _tmp()
    s = st.Settings(p)
    s["quality"], s["fov"], s["colorblind"], s["music_vol"] = "ultra", 80, True, 0.25
    assert s.save()
    t = st.Settings(p)
    assert t["quality"] == "ultra" and t["fov"] == 80.0 and t["colorblind"] is True and t["music_vol"] == 0.25


def test_clamping_and_types():
    s = st.Settings()
    s["fov"] = 500
    assert s["fov"] == 95.0
    s["master_vol"] = -3
    assert s["master_vol"] == 0.0
    s["quality"] = "ludicrous"
    assert s["quality"] == st.DEFAULTS["quality"]
    s["colorblind"] = "yes"                       # wrong type -> default
    assert s["colorblind"] is False
    s["bloom"] = float("nan")
    assert s["bloom"] == st.DEFAULTS["bloom"]
    s["steer_sens"] = True                        # bool is not a number here
    assert s["steer_sens"] == st.DEFAULTS["steer_sens"]
    try:
        s["nonsense"] = 1
        assert False
    except KeyError:
        pass


def test_corrupt_and_hostile_files():
    for content in ("", "{not json", "[1,2,3]", "null", '{"fov": "wide", "quality": 7, "extra": 1, "bloom": 99}'):
        p = _tmp()
        with open(p, "w") as fh:
            fh.write(content)
        s = st.Settings(p)                        # must never raise
        assert s["quality"] in st.QUALITIES
        assert 55.0 <= s["fov"] <= 95.0
        assert 0.0 <= s["bloom"] <= 1.6
    assert st.Settings(os.path.join(tempfile.mkdtemp(), "missing.json"))["fov"] == st.DEFAULTS["fov"]


def test_atomic_save_leaves_no_temp_files():
    p = _tmp()
    s = st.Settings(p)
    for i in range(5):
        s["fov"] = 60 + i
        assert s.save()
    assert os.listdir(os.path.dirname(p)) == ["s.json"]
    assert json.load(open(p))["fov"] == 64.0
    bad = st.Settings("/nonexistent-dir/x/s.json")
    assert bad.save() is False                    # unwritable location: reports failure, no exception


def test_reset():
    s = st.Settings()
    s["fov"] = 90
    s.reset()
    assert s["fov"] == st.DEFAULTS["fov"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        fn()
        print(f"  ok  {name}")
    print(f"\nall {len(tests)} settings tests passed")
