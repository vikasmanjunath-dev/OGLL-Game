"""
End-to-end smoke test: drives the real game through every screen under a real (software) OpenGL context.

    xvfb-run -a python3 tests/test_smoke.py          (Linux without a display)
    python3 tests/test_smoke.py                      (any desktop)

Covers: Premium + Classic rendering, switching quality at run time, the automatic fall-back when the Premium
pipeline cannot start, menus / settings / pause / game-over via keyboard AND synthetic gamepad events,
colour-blind labels, settings persistence.
"""
import os
import sys
import tempfile

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pygame

import gamepad as gp
import lumen_drift as L
import postfx

SIZE = "480x270"
DT = 1 / 60


def make(*extra, settings=None):
    argv = ["--size", SIZE, "--mute", "--seed", "3", "--fixed-dt", str(DT)]
    if settings:
        argv += ["--settings", settings]
    else:
        argv += ["--no-save"]
    return L.Game(L.parse_args(argv + list(extra)))


def frames(g, n):
    keys = pygame.key.get_pressed()
    for _ in range(n):
        g.step(DT, keys)
        g.render()
        pygame.display.flip()


def press(g, key):
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))


def pad(g, button):
    g.handle(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button, instance_id=0))


def test_premium_boots_and_renders():
    g = make("--quality", "premium")
    assert g.fx is not None, f"premium pipeline failed: {g.fx_error}"
    frames(g, 20)
    assert g.mode == "title" and g.screen is None


def test_title_menu_settings_roundtrip_and_quality_switch():
    g = make("--quality", "premium")
    frames(g, 5)
    press(g, pygame.K_DOWN)                                    # SETTINGS
    press(g, pygame.K_RETURN)
    assert g.screen == "settings"
    frames(g, 10)
    press(g, pygame.K_DOWN)                                    # tab row -> Graphics quality
    assert g.menu_settings.current().label == "Graphics quality"
    for _ in range(3):                                         # premium -> ultra -> classic -> balanced (wraps)
        press(g, pygame.K_RIGHT)
    assert g.settings["quality"] == "balanced", g.settings["quality"]
    press(g, pygame.K_LEFT)                                    # balanced -> classic
    assert g.settings["quality"] == "classic" and g.fx is None
    frames(g, 10)                                              # classic renders after the context rebuild
    press(g, pygame.K_RIGHT); press(g, pygame.K_RIGHT)
    assert g.settings["quality"] == "premium" and g.fx is not None
    frames(g, 10)
    press(g, pygame.K_ESCAPE)
    assert g.screen is None


def test_settings_tabs_and_values():
    g = make("--quality", "premium")
    g.open_screen("settings")
    frames(g, 3)
    press(g, pygame.K_e)                                       # next tab -> Audio
    assert g.menu_settings.tab == 1
    press(g, pygame.K_DOWN)
    before = g.settings["master_vol"]
    press(g, pygame.K_LEFT)
    assert g.settings["master_vol"] < before
    press(g, pygame.K_e)                                       # Gameplay
    press(g, pygame.K_DOWN)
    assert g.menu_settings.current().label == "Colour-blind labels"
    press(g, pygame.K_RETURN)
    assert g.settings["colorblind"] is True
    frames(g, 5)


def test_full_run_pause_gameover_retry_menu():
    g = make("--classic")
    press(g, pygame.K_RETURN)                                  # PLAY
    assert g.mode == "countdown"
    frames(g, 200)
    assert g.mode == "play"
    press(g, pygame.K_p)
    assert g.mode == "paused"
    s0 = g.s
    frames(g, 10)
    assert g.s == s0, "world must hold still while paused"
    press(g, pygame.K_p)
    assert g.mode == "play"
    g.autopilot_on = True
    frames(g, 120)
    g.autopilot_on = False
    g.energy = 5.0
    g.invuln = 0
    g.damage(30, "TEST", L.HAZARD, (0, 0, -g.s), "crash")
    g.energy = -1
    g.interactions(DT)
    assert g.mode == "over"
    frames(g, 150)
    press(g, pygame.K_RETURN)                                  # RETRY
    assert g.mode == "countdown"
    frames(g, 5)
    g.pause()
    assert g.mode == "paused"
    g.menu_pause.sel = 3                                       # QUIT TO MENU
    press(g, pygame.K_RETURN)
    assert g.mode == "title"
    frames(g, 5)


def test_gamepad_drives_menus_and_game():
    g = make("--classic")
    pad(g, gp.BTN_DOWN); pad(g, gp.BTN_A)                      # SETTINGS
    assert g.screen == "settings" and g.input_dev == "pad"
    pad(g, gp.BTN_RB)
    assert g.menu_settings.tab == 1
    pad(g, gp.BTN_B)
    assert g.screen is None
    pad(g, gp.BTN_UP); pad(g, gp.BTN_A)                        # PLAY
    assert g.mode == "countdown"
    frames(g, 200)
    assert g.mode == "play"
    h0 = g.hue
    g.gamepad.axes[gp.AX_LX] = 1.0                             # stick right
    u0 = g.u
    frames(g, 20)
    assert g.u > u0 + 0.5, "left stick must steer"
    g.gamepad.axes[gp.AX_LX] = 0.0
    g.gamepad.axes[gp.AX_RT] = 1.0                             # trigger rotates hue
    frames(g, 10)
    assert g.hue != h0
    g.gamepad.axes[gp.AX_RT] = 0.0
    pad(g, gp.BTN_START)
    assert g.mode == "paused"
    pad(g, gp.BTN_START)
    assert g.mode == "play"
    g.handle(pygame.event.Event(pygame.CONTROLLERDEVICEREMOVED, instance_id=0))
    assert g.mode == "paused", "unplugging the pad must pause the game"


def test_colorblind_labels_render():
    g = make("--quality", "premium", "--autoplay")
    g.settings["colorblind"] = True
    frames(g, 2)
    g.start_run(autopilot=True)
    frames(g, 500)                                             # long enough for gates to come into view


def test_fallback_when_premium_pipeline_fails():
    real = postfx.PostFX

    def boom(*a, **k):
        raise postfx.PostFXError("simulated: no framebuffer support")
    postfx.PostFX = boom
    try:
        g = make("--quality", "ultra")
    finally:
        postfx.PostFX = real
    assert g.fx is None and "simulated" in g.fx_error
    frames(g, 30)
    g.start_run(autopilot=True)
    frames(g, 60)


def test_settings_persist_between_runs():
    path = os.path.join(tempfile.mkdtemp(), "s.json")
    g = make("--classic", settings=path)
    g.set_setting("fov", 80.0)
    g.set_setting("master_vol", 0.3)
    g.settings.save()
    g2 = make(settings=path)
    assert g2.settings["fov"] == 80.0 and abs(g2.settings["master_vol"] - 0.3) < 1e-9
    assert abs(g2.audio.master - 0.3) < 1e-9


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except Exception:
            import traceback
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    pygame.quit()
    print(f"\n{len(tests) - failed}/{len(tests)} smoke tests passed")
    sys.exit(1 if failed else 0)
