"""
shaders.py - GLSL sources for the Premium renderer.

Everything is GLSL 1.20 (the version macOS's legacy OpenGL 2.1 context supports) and reads the
ordinary fixed-function state (glLightfv, glMaterialfv, matrices), so the Classic and Premium
renderers are driven by the SAME light and material calls - only the maths moves from per-vertex
(Gouraud) to per-pixel (true Phong shading).
"""

# ---------------------------------------------------------------------------------------------
# Per-pixel Phong lighting
# ---------------------------------------------------------------------------------------------
LIT_VS = """
#version 120
varying vec3 vPos;
varying vec3 vNrm;
varying vec4 vCol;
varying vec3 vObj;
void main() {
    vec4 p = gl_ModelViewMatrix * gl_Vertex;
    vPos = p.xyz;
    vNrm = gl_NormalMatrix * gl_Normal;
    vCol = gl_Color;
    vObj = gl_Vertex.xyz;
    gl_Position = gl_ProjectionMatrix * p;
}
"""

_LIGHT_BLOCK = """
    {
        vec4 lp = gl_LightSource[%(i)d].position;
        vec3 L;
        float att = 1.0;
        if (lp.w < 0.5) {
            L = normalize(lp.xyz);
        } else {
            vec3 d = lp.xyz - vPos;
            float dist = length(d);
            L = d / max(dist, 0.0001);
            att = 1.0 / (gl_LightSource[%(i)d].constantAttenuation
                       + gl_LightSource[%(i)d].linearAttenuation * dist
                       + gl_LightSource[%(i)d].quadraticAttenuation * dist * dist);
        }
        float ndl = max(dot(N, L), 0.0);
        vec3 dif = albedo * gl_LightSource[%(i)d].diffuse.rgb * ndl;
        vec3 R = reflect(-L, N);
        float rv = (ndl > 0.0) ? pow(max(dot(R, V), 0.0), shin) : 0.0;
        vec3 spc = gl_FrontMaterial.specular.rgb * gl_LightSource[%(i)d].specular.rgb * rv;
        col += uLights[%(i)d] * (albedo * gl_LightSource[%(i)d].ambient.rgb + att * (dif + spc));
    }
"""

LIT_FS = """
#version 120
uniform float uUseVCol;
uniform float uBump;
uniform float uFog;
uniform vec3  uLights;
uniform float uRim;
uniform vec3  uRimCol;
varying vec3 vPos;
varying vec3 vNrm;
varying vec4 vCol;
varying vec3 vObj;
void main() {
    vec3 N = normalize(vNrm);
    if (uBump > 0.5) {                       // ribbed tunnel panels: tilt the normal along the ring period
        vec3 tz = normalize(gl_NormalMatrix * vec3(0.0, 0.0, 1.0));
        N = normalize(N + tz * (sin(vObj.z * 2.5132741) * 0.32));
    }
    vec3 V = normalize(-vPos);
    vec3 albedo = mix(gl_FrontMaterial.diffuse.rgb, vCol.rgb, uUseVCol);
    float shin = max(gl_FrontMaterial.shininess, 1.0);
    vec3 col = albedo * gl_LightModel.ambient.rgb + gl_FrontMaterial.emission.rgb;
""" + (_LIGHT_BLOCK % {"i": 0}) + (_LIGHT_BLOCK % {"i": 1}) + (_LIGHT_BLOCK % {"i": 2}) + """
    float fr = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    col += uRimCol * fr * uRim;
    float dist = length(vPos);
    float f = exp(-(uFog * dist) * (uFog * dist));
    gl_FragColor = vec4(col * f, 1.0);
}
"""

# ---------------------------------------------------------------------------------------------
# Emissive / additive geometry (grid, glow sprites, particles, trail) - HDR gain + distance fog
# ---------------------------------------------------------------------------------------------
GLOW_VS = """
#version 120
varying vec4 vCol;
varying vec2 vTex;
varying float vDist;
void main() {
    vec4 p = gl_ModelViewMatrix * gl_Vertex;
    vDist = length(p.xyz);
    vCol = gl_Color;
    vTex = gl_MultiTexCoord0.xy;
    gl_Position = gl_ProjectionMatrix * p;
}
"""

GLOW_FS = """
#version 120
uniform sampler2D uTex;
uniform float uUseTex;
uniform float uGain;
uniform float uFog;
varying vec4 vCol;
varying vec2 vTex;
varying float vDist;
void main() {
    vec4 c = vCol;
    if (uUseTex > 0.5) c *= texture2D(uTex, vTex);
    float f = exp(-(uFog * vDist) * (uFog * vDist));
    gl_FragColor = vec4(c.rgb * uGain * f, c.a);
}
"""

# ---------------------------------------------------------------------------------------------
# Full-screen passes
# ---------------------------------------------------------------------------------------------
QUAD_VS = """
#version 120
varying vec2 vUV;
void main() {
    vUV = gl_Vertex.xy * 0.5 + 0.5;
    gl_Position = vec4(gl_Vertex.xy, 0.0, 1.0);
}
"""

BRIGHT_FS = """
#version 120
uniform sampler2D uTex;
uniform vec2 uTexel;
uniform float uThresh;
varying vec2 vUV;
vec3 prefilter(vec3 c) {
    float l = max(c.r, max(c.g, c.b));
    float knee = 0.35;
    float soft = clamp(l - uThresh + knee, 0.0, 2.0 * knee);
    soft = soft * soft / (4.0 * knee + 0.0001);
    float k = max(soft, l - uThresh) / max(l, 0.0001);
    return c * k;
}
void main() {
    vec2 t = uTexel * 0.5;
    vec3 c = texture2D(uTex, vUV + vec2(-t.x, -t.y)).rgb;
    c += texture2D(uTex, vUV + vec2( t.x, -t.y)).rgb;
    c += texture2D(uTex, vUV + vec2(-t.x,  t.y)).rgb;
    c += texture2D(uTex, vUV + vec2( t.x,  t.y)).rgb;
    gl_FragColor = vec4(prefilter(c * 0.25), 1.0);
}
"""

DOWN_FS = """
#version 120
uniform sampler2D uTex;
uniform vec2 uTexel;
varying vec2 vUV;
void main() {
    vec2 t = uTexel * 0.5;
    vec3 c = texture2D(uTex, vUV + vec2(-t.x, -t.y)).rgb;
    c += texture2D(uTex, vUV + vec2( t.x, -t.y)).rgb;
    c += texture2D(uTex, vUV + vec2(-t.x,  t.y)).rgb;
    c += texture2D(uTex, vUV + vec2( t.x,  t.y)).rgb;
    gl_FragColor = vec4(c * 0.25, 1.0);
}
"""

BLUR_FS = """
#version 120
uniform sampler2D uTex;
uniform vec2 uDir;
varying vec2 vUV;
void main() {
    vec3 c = texture2D(uTex, vUV).rgb * 0.2270270270;
    c += texture2D(uTex, vUV + uDir * 1.3846153846).rgb * 0.3162162162;
    c += texture2D(uTex, vUV - uDir * 1.3846153846).rgb * 0.3162162162;
    c += texture2D(uTex, vUV + uDir * 3.2307692308).rgb * 0.0702702703;
    c += texture2D(uTex, vUV - uDir * 3.2307692308).rgb * 0.0702702703;
    gl_FragColor = vec4(c, 1.0);
}
"""

COMPOSITE_FS = """
#version 120
uniform sampler2D uScene;
uniform sampler2D uB0;
uniform sampler2D uB1;
uniform sampler2D uB2;
uniform sampler2D uB3;
uniform vec4  uBW;          // weight of each bloom level
uniform vec2  uTexel;
uniform float uTime;
uniform float uSpeed;       // 0..1
uniform float uBloom;
uniform float uExposure;
uniform float uGrain;
uniform float uAber;
uniform float uRadial;
uniform float uVig;
uniform float uFxaa;
uniform vec4  uFlash;       // rgb + strength
varying vec2 vUV;

vec3 tm(vec3 c) {                           // filmic shoulder: untouched below 0.75, rolls off to 1.0
    vec3 k = max(c - 0.75, 0.0);
    return min(c, vec3(0.75)) + 0.25 * (1.0 - exp(-k * 4.0));
}
vec3 S(vec2 uv) { return tm(texture2D(uScene, uv).rgb * uExposure); }

vec3 fxaa(vec2 uv) {
    vec3 M  = S(uv);
    if (uFxaa < 0.5) return M;
    vec3 NW = S(uv + vec2(-1.0, -1.0) * uTexel);
    vec3 NE = S(uv + vec2( 1.0, -1.0) * uTexel);
    vec3 SW = S(uv + vec2(-1.0,  1.0) * uTexel);
    vec3 SE = S(uv + vec2( 1.0,  1.0) * uTexel);
    vec3 lw = vec3(0.299, 0.587, 0.114);
    float lM = dot(M, lw), lNW = dot(NW, lw), lNE = dot(NE, lw), lSW = dot(SW, lw), lSE = dot(SE, lw);
    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    vec2 dir;
    dir.x = -((lNW + lNE) - (lSW + lSE));
    dir.y =  ((lNW + lSW) - (lNE + lSE));
    float reduce = max((lNW + lNE + lSW + lSE) * 0.03125, 0.0078125);
    float rcp = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
    dir = clamp(dir * rcp, vec2(-8.0), vec2(8.0)) * uTexel;
    vec3 A = 0.5 * (S(uv + dir * (1.0 / 3.0 - 0.5)) + S(uv + dir * (2.0 / 3.0 - 0.5)));
    vec3 B = A * 0.5 + 0.25 * (S(uv + dir * -0.5) + S(uv + dir * 0.5));
    float lB = dot(B, lw);
    return (lB < lMin || lB > lMax) ? A : B;
}

void main() {
    vec2 uv = vUV;
    vec2 d = uv - 0.5;
    float r2 = dot(d, d);
    vec2 off = d * (uAber * (0.0015 + 0.011 * uSpeed) * (0.4 + 3.0 * r2));
    vec3 col;
    col = fxaa(uv);
    if (uAber > 0.001) {                    // only the red/blue fringes are fetched again: cheap on integrated GPUs
        col.r = S(uv + off).r;
        col.b = S(uv - off).b;
    }
    if (uRadial > 0.001) {                  // cheap radial blur that grows toward the screen edge
        vec3 acc = vec3(0.0);
        for (int i = 0; i < 6; i++) {
            float t = float(i) / 5.0;
            acc += S(uv - d * uRadial * t);
        }
        acc /= 6.0;
        col = mix(col, acc, clamp(r2 * 3.2 * uRadial * 14.0, 0.0, 0.75));
    }
    vec3 bloom = texture2D(uB0, uv).rgb * uBW.x + texture2D(uB1, uv).rgb * uBW.y
               + texture2D(uB2, uv).rgb * uBW.z + texture2D(uB3, uv).rgb * uBW.w;
    col += tm(bloom * uBloom);
    col = tm(col);
    col *= 1.0 - uVig * smoothstep(0.30, 0.95, length(d) * 1.45);
    float g = fract(sin(dot(uv * vec2(1731.0, 947.0) + vec2(uTime * 37.0, uTime * 11.0), vec2(12.9898, 78.233))) * 43758.5453);
    col += (g - 0.5) * uGrain;
    col += uFlash.rgb * uFlash.a;
    gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
"""

# ---------------------------------------------------------------------------------------------
# UI: anti-aliased rounded rectangle, optional frosted-glass backdrop + soft shadow
# ---------------------------------------------------------------------------------------------
ROUNDRECT_VS = """
#version 120
varying vec2 vPosL;
void main() {
    vPosL = gl_Vertex.xy;
    gl_Position = gl_ProjectionMatrix * gl_ModelViewMatrix * gl_Vertex;
}
"""

ROUNDRECT_FS = """
#version 120
uniform vec4  uRect;        // centre.xy, half-size.xy   (logical HUD units)
uniform float uRadius;
uniform vec4  uFill;
uniform vec4  uBorder;
uniform float uGlass;       // 0..1 how much of the blurred backdrop shows through
uniform float uShadow;      // 0..1
uniform float uPx;          // logical units per screen pixel
uniform float uAlpha;       // overall opacity (entrance / fade animations)
uniform vec2  uRes;         // framebuffer size in pixels
uniform sampler2D uBackdrop;
varying vec2 vPosL;
void main() {
    vec2 p = vPosL - uRect.xy;
    vec2 q = abs(p) - (uRect.zw - vec2(uRadius));
    float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - uRadius;
    float aa = uPx;
    float inside = 1.0 - smoothstep(-aa, aa, sd);
    float shadow = uShadow * exp(-max(sd, 0.0) / (uRadius * 0.55 + 6.0)) * 0.55 * (1.0 - smoothstep(14.0, 42.0, sd));
    vec3 base = uFill.rgb;
    float a = uFill.a;
    if (uGlass > 0.001) {
        vec3 bg = texture2D(uBackdrop, gl_FragCoord.xy / uRes).rgb;
        bg = bg / (1.0 + 0.55 * bg);
        bg = bg * 0.82 + vec3(0.02);
        base = mix(bg, uFill.rgb, clamp(uFill.a, 0.0, 1.0));
        a = mix(uFill.a, 1.0, uGlass);
    }
    float top = clamp((vPosL.y - (uRect.y - uRect.w)) / max(2.0 * uRect.w, 1.0), 0.0, 1.0);
    base += vec3(0.055) * (1.0 - top);      // soft top-light, like a glass sheen
    float edge = 1.0 - smoothstep(0.0, aa * 2.2, abs(sd + aa * 1.2));
    vec3 rgb = mix(base, uBorder.rgb, edge * uBorder.a);
    float alpha = inside * max(a, edge * uBorder.a);
    float shadowA = (1.0 - inside) * shadow;
    float outA = alpha + shadowA * (1.0 - alpha);
    vec3 outC = (rgb * alpha + vec3(0.0) * shadowA * (1.0 - alpha)) / max(outA, 0.0001);
    gl_FragColor = vec4(outC, outA * uAlpha);
}
"""
