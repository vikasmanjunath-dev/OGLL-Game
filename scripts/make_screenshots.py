#!/usr/bin/env python3
"""
Regenerate the screenshots in docs/ by driving the real game through its screens (deterministic, no human).

    python3 scripts/make_screenshots.py                 # 1280x720 Premium (+ Classic for the comparison image)
    python3 scripts/make_screenshots.py --size 960x540 --out /tmp/shots

On a headless Linux box:  xvfb-run -a python3 scripts/make_screenshots.py
Each scene runs in its own process (a fresh OpenGL context), so a crash in one cannot spoil the rest.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scene_main(a):
    """Runs INSIDE a child process: play one scripted scene and exit."""
    sys.path.insert(0, ROOT)
    quality = "classic" if a.scene == "classic" else "premium"
    sys.argv = ["x", "--size", a.size, "--mute", "--no-save", "--fixed-dt", "0.0166", "--quality", quality]
    import lumen_drift as L

    out = a.out
    os.makedirs(out, exist_ok=True)
    frame = [0]
    todo = {}

    def at(f, fn):
        todo[f] = fn

    def shot(name):
        return lambda g: setattr(g, "want_shot", os.path.join(out, name + ".png"))

    def quit_(g):
        g.running = False

    if a.scene == "menus":                                   # title, settings, gameplay, pause, game over
        at(70, shot("title"))
        at(75, lambda g: g.do_action("down"))
        at(112, lambda g: g.do_action("confirm"))           # SETTINGS
        at(150, shot("settings"))
        at(152, lambda g: [g.do_action("down"), g.do_action("down"), g.do_action("right"), g.do_action("right")])
        at(192, lambda g: [g.do_action("up"), g.do_action("up"), g.do_action("right")])
        at(232, lambda g: [g.do_action("right"), g.do_action("down"), g.do_action("confirm")])   # Gameplay tab, colour-blind labels ON
        at(272, lambda g: g.do_action("back"))
        at(276, lambda g: [g.do_action("up"), g.do_action("confirm")])                           # PLAY
        at(300, lambda g: setattr(g, "autopilot_on", True))
        at(520, shot("gameplay"))
        at(530, lambda g: g.do_action("pause"))
        at(560, shot("pause"))
        at(562, lambda g: g.do_action("pause"))
        at(702, lambda g: [setattr(g, "autopilot_on", False), setattr(g, "energy", 0.5), setattr(g, "invuln", 0)])
        at(704, lambda g: g.damage(30.0, "HULL IMPACT", L.HAZARD, (0, 0, -g.s), "crash"))
        at(850, shot("game_over"))
        at(851, quit_)
    else:                                                    # lab | ortho | classic | premium : one frame of autopilot flight
        sys.argv.append("--autoplay")
        at(5, lambda g: g.start_run(autopilot=True))
        if a.scene == "lab":
            at(20, lambda g: setattr(g, "show_lab", True))
        if a.scene == "ortho":
            at(20, lambda g: [setattr(g, "ortho_cam", True), setattr(g, "show_lab", True)])
        names = {"lab": "lab_overlay", "ortho": "projection_lab_ortho", "classic": "classic", "premium": "premium"}
        at(440, shot(names[a.scene]))
        at(442, quit_)

    orig = L.Game.step

    def step(self, dt, keys):
        frame[0] += 1
        fn = todo.get(frame[0])
        if fn:
            fn(self)
        return orig(self, dt, keys)

    L.Game.step = step
    L.main()


def compare(out, docs):
    from PIL import Image, ImageDraw, ImageFont
    a = Image.open(os.path.join(out, "classic.png")).convert("RGB")
    b = Image.open(os.path.join(out, "premium.png")).convert("RGB")
    w, h = a.size
    c = Image.new("RGB", (w * 2 + 8, h + 56), (8, 10, 16))
    c.paste(a, (0, 0))
    c.paste(b, (w + 8, 0))
    c = c.resize((c.width // 2, c.height // 2), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    try:
        f = ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "Inter-SemiBold.otf"), 15)
    except Exception:
        f = None
    y = c.height - 14
    d.text((c.width // 4, y), "CLASSIC  -  per-vertex lighting", fill=(210, 225, 245), font=f, anchor="mm")
    d.text((c.width * 3 // 4, y), "PREMIUM  -  per-pixel, HDR bloom, FXAA", fill=(210, 225, 245), font=f, anchor="mm")
    c.save(os.path.join(docs, "classic_vs_premium.png"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"), help="where the PNGs go (default: docs/)")
    ap.add_argument("--scene", choices=["menus", "lab", "ortho", "classic", "premium"], help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.scene:
        return scene_main(a)
    tmp = os.path.join(a.out, "_tmp")
    for scene in ("menus", "lab", "ortho", "classic", "premium"):
        print(f"[{scene}] ...", flush=True)
        dest = a.out if scene in ("menus", "lab", "ortho") else tmp
        subprocess.run([sys.executable, __file__, "--scene", scene, "--size", a.size, "--out", dest], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        compare(tmp, a.out)
    except ImportError:
        print("Pillow not installed: skipped classic_vs_premium.png (pip install pillow)")
    for f in ("classic.png", "premium.png"):
        p = os.path.join(tmp, f)
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(tmp):
        os.rmdir(tmp)
    print("done ->", a.out)


if __name__ == "__main__":
    main()
