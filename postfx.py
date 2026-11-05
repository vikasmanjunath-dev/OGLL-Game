"""
postfx.py - the Premium renderer's GPU plumbing.

    scene (HDR FBO) -> bright-pass -> dual-filter bloom chain -> composite (tonemap, FXAA, aberration,
    radial speed blur, vignette, grain) -> screen

Everything is GLSL 1.20 / OpenGL 2.1 so it also runs on macOS's legacy context.  Any failure while
building (no FBO support, shader compile error...) raises PostFXError; the game catches it and drops
back to the Classic fixed-function renderer, so the game can never end up on a black screen.
"""
from __future__ import annotations

import ctypes

from OpenGL.GL import *  # noqa: F401,F403
from OpenGL.GL.framebufferobjects import (GL_COLOR_ATTACHMENT0, GL_DEPTH_ATTACHMENT, GL_FRAMEBUFFER,
                                           GL_FRAMEBUFFER_COMPLETE, GL_RENDERBUFFER, glBindFramebuffer,
                                           glBindRenderbuffer, glCheckFramebufferStatus, glDeleteFramebuffers,
                                           glDeleteRenderbuffers, glFramebufferRenderbuffer,
                                           glFramebufferTexture2D, glGenFramebuffers, glGenRenderbuffers,
                                           glRenderbufferStorage)

import shaders as sh

GL_RGBA16F_ = 0x881A


class PostFXError(RuntimeError):
    pass


def compile_shader(kind, src):
    s = glCreateShader(kind)
    glShaderSource(s, src)
    glCompileShader(s)
    if not glGetShaderiv(s, GL_COMPILE_STATUS):
        log = glGetShaderInfoLog(s)
        log = log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log)
        glDeleteShader(s)
        raise PostFXError("shader compile failed:\n" + log)
    return s


class Program:
    """A linked GLSL program with cached uniform locations. Unknown/optimised-away uniforms are ignored."""

    def __init__(self, vs, fs, name=""):
        self.name = name
        v, f = compile_shader(GL_VERTEX_SHADER, vs), compile_shader(GL_FRAGMENT_SHADER, fs)
        self.id = glCreateProgram()
        glAttachShader(self.id, v)
        glAttachShader(self.id, f)
        glLinkProgram(self.id)
        glDeleteShader(v)
        glDeleteShader(f)
        if not glGetProgramiv(self.id, GL_LINK_STATUS):
            log = glGetProgramInfoLog(self.id)
            log = log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log)
            raise PostFXError(f"program '{name}' link failed:\n{log}")
        self._loc = {}
        self._val = {}

    def use(self):
        glUseProgram(self.id)

    def loc(self, name):
        if name not in self._loc:
            self._loc[name] = glGetUniformLocation(self.id, name)
        return self._loc[name]

    def set(self, name, *v):
        """Set a uniform (the program must be bound). Skips redundant updates."""
        if self._val.get(name) == v:
            return
        L = self.loc(name)
        if L < 0:
            return
        self._val[name] = v
        n = len(v)
        if n == 1:
            glUniform1f(L, float(v[0]))
        elif n == 2:
            glUniform2f(L, *map(float, v))
        elif n == 3:
            glUniform3f(L, *map(float, v))
        else:
            glUniform4f(L, *map(float, v))

    def seti(self, name, value):
        """Set an integer uniform (sampler unit)."""
        if self._val.get(name) == (value,):
            return
        L = self.loc(name)
        if L >= 0:
            self._val[name] = (value,)
            glUniform1i(L, int(value))

    def forget(self):
        self._val.clear()


def _quad():
    glBegin(GL_QUADS)
    glVertex2f(-1, -1)
    glVertex2f(1, -1)
    glVertex2f(1, 1)
    glVertex2f(-1, 1)
    glEnd()


class Target:
    """A colour texture (+ optional depth renderbuffer) and the FBO that draws into it."""

    def __init__(self, w, h, hdr=True, depth=False, linear=True):
        self.w, self.h = max(1, int(w)), max(1, int(h))
        self.tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        f = GL_LINEAR if linear else GL_NEAREST
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, f)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, f)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        if hdr:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F_, self.w, self.h, 0, GL_RGBA, GL_FLOAT, None)
        else:
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.w, self.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        self.fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.tex, 0)
        self.rb = None
        if depth:
            self.rb = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.rb)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, self.w, self.h)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self.rb)
        ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if not ok:
            self.free()
            raise PostFXError(f"framebuffer incomplete ({'HDR' if hdr else 'LDR'} {self.w}x{self.h})")

    def bind(self):
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.w, self.h)

    def free(self):
        try:
            glDeleteFramebuffers(1, [self.fbo])
            glDeleteTextures([self.tex])
            if self.rb is not None:
                glDeleteRenderbuffers(1, [self.rb])
        except Exception:
            pass


class PostFX:
    def __init__(self, size, scale=1.0, bloom_levels=4):
        self.full = (int(size[0]), int(size[1]))
        self.scale = float(scale)
        self.levels = max(1, min(4, int(bloom_levels)))
        self.sw = max(2, int(self.full[0] * self.scale))
        self.sh = max(2, int(self.full[1] * self.scale))
        self.hdr = True
        try:
            self._targets()
        except PostFXError:
            self.free()
            self.hdr = False                                    # RGBA8 fallback (no float render targets)
            self._targets()
        self.p_lit = Program(sh.LIT_VS, sh.LIT_FS, "lit")
        self.p_glow = Program(sh.GLOW_VS, sh.GLOW_FS, "glow")
        self.p_bright = Program(sh.QUAD_VS, sh.BRIGHT_FS, "bright")
        self.p_down = Program(sh.QUAD_VS, sh.DOWN_FS, "down")
        self.p_blur = Program(sh.QUAD_VS, sh.BLUR_FS, "blur")
        self.p_comp = Program(sh.QUAD_VS, sh.COMPOSITE_FS, "composite")
        self.active = None
        self.backdrop_ready = False
        self.stats = {"hdr": self.hdr, "scene": (self.sw, self.sh)}
        glUseProgram(0)

    # ------------------------------------------------------------------ resources
    def _targets(self):
        self.scene = Target(self.sw, self.sh, self.hdr, depth=True)
        self.A, self.B = [], []
        w, h = self.sw, self.sh
        for _ in range(4):
            w, h = max(2, w // 2), max(2, h // 2)
            self.A.append(Target(w, h, self.hdr))
            self.B.append(Target(w, h, self.hdr))
        # frosted-glass backdrop for UI panels: scene at 1/4 res, blurred
        self.bd = [Target(max(2, self.sw // 4), max(2, self.sh // 4), self.hdr),
                   Target(max(2, self.sw // 4), max(2, self.sh // 4), self.hdr)]

    def free(self):
        for t in [getattr(self, "scene", None)] + getattr(self, "A", []) + getattr(self, "B", []) + getattr(self, "bd", []):
            if t is not None:
                t.free()
        self.A, self.B, self.bd, self.scene = [], [], [], None

    # ------------------------------------------------------------------ scene pass helpers
    def begin_scene(self):
        self.scene.bind()
        self.backdrop_ready = False

    def use_lit(self, bump=False, vcol=False, lights=(1, 1, 0), fog=0.011, rim=0.0, rim_col=(1, 1, 1)):
        p = self.p_lit
        if self.active is not p:
            p.use()
            self.active = p
        p.set("uBump", 1.0 if bump else 0.0)
        p.set("uUseVCol", 1.0 if vcol else 0.0)
        p.set("uLights", *lights)
        p.set("uFog", fog)
        p.set("uRim", rim)
        p.set("uRimCol", *rim_col)

    def use_glow(self, gain=1.0, tex=False, fog=0.011):
        p = self.p_glow
        if self.active is not p:
            p.use()
            self.active = p
        p.set("uGain", gain)
        p.set("uUseTex", 1.0 if tex else 0.0)
        p.set("uFog", fog)
        p.seti("uTex", 0)

    def off(self):
        if self.active is not None:
            glUseProgram(0)
            self.active = None

    # ------------------------------------------------------------------ full-screen passes
    def _pass(self, prog, target, **bind):
        if target is None:
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            glViewport(0, 0, *self.full)
        else:
            target.bind()
        prog.use()
        for i, tex in enumerate(bind.get("tex", ())):
            glActiveTexture(GL_TEXTURE0 + i)
            glBindTexture(GL_TEXTURE_2D, tex)
            prog.seti(("uTex", "uB0", "uB1", "uB2", "uB3")[i] if prog is not self.p_comp else
                      ("uScene", "uB0", "uB1", "uB2", "uB3")[i], i)
        glActiveTexture(GL_TEXTURE0)
        _quad()

    def _blur(self, i, passes=1):
        a, b = self.A[i], self.B[i]
        p = self.p_blur
        for _ in range(passes):
            p.use()
            p.set("uDir", 1.0 / a.w, 0.0)
            self._pass(p, b, tex=(a.tex,))
            p.set("uDir", 0.0, 1.0 / a.h)
            self._pass(p, a, tex=(b.tex,))

    def bloom(self, threshold=1.0):
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glDisable(GL_LIGHTING)
        glDisable(GL_FOG)
        self.off()
        self.p_bright.use()
        self.p_bright.set("uTexel", 1.0 / self.sw, 1.0 / self.sh)
        self.p_bright.set("uThresh", threshold)
        self._pass(self.p_bright, self.A[0], tex=(self.scene.tex,))
        for i in range(1, self.levels):
            self.p_down.use()
            self.p_down.set("uTexel", 1.0 / self.A[i - 1].w, 1.0 / self.A[i - 1].h)
            self._pass(self.p_down, self.A[i], tex=(self.A[i - 1].tex,))
        for i in range(self.levels):
            self._blur(i, 1 if i < 2 else 2)

    def make_backdrop(self):
        """Blurred, shrunk copy of the finished 3D scene for frosted-glass UI panels (once per frame, on demand)."""
        if self.backdrop_ready:
            return
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        self.off()
        self.p_down.use()
        self.p_down.set("uTexel", 1.0 / self.sw, 1.0 / self.sh)
        self._pass(self.p_down, self.bd[0], tex=(self.scene.tex,))
        p = self.p_blur
        for _ in range(2):
            p.use()
            p.set("uDir", 1.6 / self.bd[0].w, 0.0)
            self._pass(p, self.bd[1], tex=(self.bd[0].tex,))
            p.set("uDir", 0.0, 1.6 / self.bd[0].h)
            self._pass(p, self.bd[0], tex=(self.bd[1].tex,))
        self.backdrop_ready = True

    def finish(self, *, time=0.0, speed=0.0, bloom=0.85, exposure=1.0, grain=0.03, aberration=1.0,
               radial=0.0, vignette=0.35, fxaa=True, flash=(0, 0, 0, 0)):
        """Bloom + composite the HDR scene onto the real screen."""
        self.bloom(threshold=1.0)
        w = (0.55, 0.65, 0.75, 0.85)
        bw = [w[i] if i < self.levels else 0.0 for i in range(4)]
        tex = [self.scene.tex] + [self.A[min(i, self.levels - 1)].tex for i in range(4)]
        p = self.p_comp
        p.use()
        p.set("uBW", *bw)
        p.set("uTexel", 1.0 / self.sw, 1.0 / self.sh)
        p.set("uTime", time % 100.0)
        p.set("uSpeed", speed)
        p.set("uBloom", bloom)
        p.set("uExposure", exposure)
        p.set("uGrain", grain)
        p.set("uAber", aberration)
        p.set("uRadial", radial)
        p.set("uVig", vignette)
        p.set("uFxaa", 1.0 if fxaa else 0.0)
        p.set("uFlash", *flash)
        self._pass(p, None, tex=tex)
        glUseProgram(0)
        self.active = None
        glViewport(0, 0, *self.full)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)


class RoundRect:
    """Anti-aliased rounded rectangles (SDF in a fragment shader) for the glass UI.
    Works with or without the Premium pipeline: with a backdrop texture panels turn into frosted glass."""

    def __init__(self):
        self.prog = Program(sh.ROUNDRECT_VS, sh.ROUNDRECT_FS, "roundrect")

    def draw(self, x, y, w, h, radius, fill, border=(0, 0, 0, 0), glass=0.0, shadow=0.0, px=1.0,
             res=(1, 1), backdrop=None, alpha=1.0):
        p = self.prog
        p.use()
        pad = 44.0 if shadow > 0 else 3.0
        p.set("uRect", x + w / 2, y + h / 2, w / 2, h / 2)
        p.set("uRadius", max(1.0, min(radius, w / 2, h / 2)))
        p.set("uFill", *fill)
        p.set("uBorder", *border)
        g = glass if backdrop is not None else 0.0
        p.set("uGlass", g)
        p.set("uShadow", shadow)
        p.set("uPx", px)
        p.set("uAlpha", max(0.0, min(1.0, alpha)))
        p.set("uRes", float(res[0]), float(res[1]))
        if g > 0:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, backdrop)
            p.seti("uBackdrop", 0)
        glBegin(GL_QUADS)
        glVertex2f(x - pad, y - pad)
        glVertex2f(x + w + pad, y - pad)
        glVertex2f(x + w + pad, y + h + pad)
        glVertex2f(x - pad, y + h + pad)
        glEnd()
        glUseProgram(0)
