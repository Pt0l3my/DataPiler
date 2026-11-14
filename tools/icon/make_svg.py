"""DataPiler's icon (S65): an original blood-red katana in a rising slash, its trail streaming off the whole blade,
with blood drops flung from the tip's path. Three levels of detail, so nothing is too small to see at 16 px. Our own
drawing; no game art is used. Writes datapiler-large.svg, -medium.svg and -small.svg in the current folder."""
import math

H = (38.0, 222.0)          # the pivot: the end of the handle, where the hands are
A1 = -57.0                 # the blade's angle now (degrees; screen y points down): the tip up and to the right
A0 = -31.0                 # its angle at the start of the trail
HANDLE, BLADE = 60.0, 150.0


def unit(a):
    return math.cos(math.radians(a)), math.sin(math.radians(a))


def pt(r, a):
    ux, uy = unit(a)
    return H[0] + r * ux, H[1] + r * uy


def sector(r0, r1, a0, a1):
    """An annular sector around H from angle a0 to a1 (a0 > a1: counter-clockwise on screen)."""
    p0, p1, q1, q0 = pt(r1, a0), pt(r1, a1), pt(r0, a1), pt(r0, a0)
    return (f"M {p0[0]:.1f} {p0[1]:.1f} A {r1} {r1} 0 0 0 {p1[0]:.1f} {p1[1]:.1f} L {q1[0]:.1f} {q1[1]:.1f} "
            f"A {r0} {r0} 0 0 1 {q0[0]:.1f} {q0[1]:.1f} Z")


def arc(r, a0, a1):
    p0, p1 = pt(r, a0), pt(r, a1)
    return f"M {p0[0]:.1f} {p0[1]:.1f} A {r} {r} 0 0 0 {p1[0]:.1f} {p1[1]:.1f}"


def streak(r, a_start, w, wave=0.0, phase=0.0):
    """A tapered strand of the trail at radius r: nothing at a_start, w wide at the blade, a little wavy."""
    outer, inner = [], []
    n = 28
    for i in range(n + 1):
        f = i / n                                    # 0 where the strand begins, 1 at the blade
        a = a_start + (A1 - a_start) * f
        half = w * 0.5 * (f ** 1.4)
        rr = r + wave * math.sin(phase + f * 2.6 * math.pi) * (1 - f * 0.6)
        outer.append(pt(rr + half, a))
        inner.append(pt(rr - half, a))
    pts = outer + inner[::-1]
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"


def drop(cx, cy, r, rot, hl=True):
    """A teardrop whose tail points along rot (degrees; 0 = up)."""
    p = (f"M 0 {-2.3*r:.1f} C {0.55*r:.1f} {-1.2*r:.1f}, {r:.1f} {-0.35*r:.1f}, {r:.1f} {0.15*r:.1f} "
         f"A {r:.1f} {r:.1f} 0 1 1 {-r:.1f} {0.15*r:.1f} C {-r:.1f} {-0.35*r:.1f}, {-0.55*r:.1f} {-1.2*r:.1f}, 0 {-2.3*r:.1f} Z")
    out = (f'<g transform="translate({cx:.1f} {cy:.1f}) rotate({rot})"><path d="{p}" fill="url(#drop)" '
           f'stroke="#3a0008" stroke-width="{max(1.5, r*0.12):.1f}"/>')
    if hl:
        out += (f'<ellipse cx="{-0.38*r:.1f}" cy="0" rx="{0.22*r:.1f}" ry="{0.34*r:.1f}" fill="#ffffff" opacity="0.55" '
                f'transform="rotate(25)"/>')
    return out + "</g>"


def blade(bw, L):
    """The katana's blade along a gentle curve from the guard to the tip; its edge leads the swing (upper left)."""
    g = pt(HANDLE, A1)
    t = pt(HANDLE + BLADE, A1)
    ux, uy = unit(A1)
    nx, ny = uy, -ux                          # the normal towards the upper left: the edge's side
    mid = ((g[0] + t[0]) / 2 + nx * 9, (g[1] + t[1]) / 2 + ny * 9)    # the curve (sori) bows towards the edge
    def at(s):
        u = 1 - s
        return (u * u * g[0] + 2 * u * s * mid[0] + s * s * t[0], u * u * g[1] + 2 * u * s * mid[1] + s * s * t[1])
    def tangent(s):
        return (2 * (1 - s) * (mid[0] - g[0]) + 2 * s * (t[0] - mid[0]), 2 * (1 - s) * (mid[1] - g[1]) + 2 * s * (t[1] - mid[1]))
    edge, spine = [], []
    for i in range(49):
        s = i / 48
        w = bw * (1 - 0.18 * s) * ((max(0.0, 1 - (s - 0.86) / 0.14)) ** 0.6 if s > 0.86 else 1.0)
        x, y = at(s); dx, dy = tangent(s); ln = math.hypot(dx, dy); px, py = dy / ln, -dx / ln
        edge.append((x + px * w * 0.5, y + py * w * 0.5))
        spine.append((x - px * w * 0.5, y - py * w * 0.5))
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in edge + spine[::-1]) + " Z"
    out = (f'<path d="{d}" fill="url(#blade)" stroke="#220005" stroke-width="{3 if L else 4}" '
           f'stroke-linejoin="round"/>')
    if L:
        hl = "M " + " L ".join(f"{x + (sx - x) * 0.2:.1f} {y + (sy - y) * 0.2:.1f}" for (x, y), (sx, sy) in zip(edge[2:44], spine[2:44]))
        out += f'<path d="{hl}" fill="none" stroke="#ff7482" stroke-width="2.4" stroke-linecap="round" opacity="0.95"/>'
    return out


def svg(level):
    L, M, S = level == "large", level == "medium", level == "small"
    bw = 15 if L else (21 if M else 30)
    hw = 18 if L else (24 if M else 30)
    parts = ['''<defs>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#34121a"/><stop offset="1" stop-color="#0d0507"/></linearGradient>
  <linearGradient id="blade" gradientUnits="userSpaceOnUse" x1="120" y1="104" x2="132" y2="112">
    <stop offset="0" stop-color="#e8283f"/><stop offset="0.5" stop-color="#b80c26"/><stop offset="1" stop-color="#5c0411"/></linearGradient>
  <radialGradient id="drop" cx="0.4" cy="0.55" r="0.75"><stop offset="0" stop-color="#ff3a4e"/><stop offset="1" stop-color="#a8001a"/></radialGradient>
  <clipPath id="inTile"><rect x="10" y="10" width="236" height="236" rx="50"/></clipPath>
</defs>''',
             '<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#tile)" stroke="#7a2232" stroke-width="5"/>']
    # the trail: the ground the whole blade swept, faint and dark where the swing began, deep and bright at the
    # blade; thin layers stacked towards the blade, each a shade brighter, so the fade has no seams
    r_in, r_out = HANDLE + 8, HANDLE + BLADE + 2
    trail = ['<g clip-path="url(#inTile)">']
    n = 18 if L else (12 if M else 8)
    dark, bright = (110, 0, 20), (222, 26, 52)
    for k in range(n):
        a = A0 + (A1 - A0) * k / n
        f = k / max(1, n - 1)
        col = "#%02x%02x%02x" % tuple(round(d + (b - d) * f) for d, b in zip(dark, bright))
        trail.append(f'<path d="{sector(r_in, r_out, a, A1)}" fill="{col}" opacity="{0.075 if L else (0.1 if M else 0.13):.3f}"/>')
    # strands along the trail, as if each part of the blade left its own line of blood, tapering away from it
    if L:
        strands = ((r_out - 5, A0 + 1, 7.0, 2.5, 0.0, "#ff4a5c", 0.95), (r_out - 24, A0 + 6, 5.5, 3.0, 1.3, "#e8203c", 0.85),
                   (r_out - 45, A0 + 2, 6.0, 2.5, 2.1, "#ff4a5c", 0.75), (r_out - 70, A0 + 9, 5.0, 3.0, 0.6, "#d0142f", 0.7),
                   (r_out - 96, A0 + 5, 4.5, 2.5, 1.8, "#ff4a5c", 0.6), (r_out - 122, A0 + 11, 4.0, 2.0, 2.7, "#d0142f", 0.55),
                   (r_out - 14, A0 + 12, 3.0, 2.0, 0.9, "#5a000e", 0.8), (r_out - 58, A0 + 14, 3.0, 2.0, 2.4, "#5a000e", 0.7))
    elif M:
        strands = ((r_out - 7, A0 + 2, 11.0, 3.0, 0.0, "#ff4a5c", 0.95), (r_out - 52, A0 + 6, 9.0, 3.0, 1.6, "#e8203c", 0.8),
                   (r_out - 100, A0 + 8, 8.0, 2.5, 2.4, "#ff4a5c", 0.65))
    else:
        strands = ((r_out - 10, A0 + 3, 16.0, 0.0, 0.0, "#ff4a5c", 0.95), (r_out - 70, A0 + 8, 13.0, 0.0, 0.0, "#e8203c", 0.8))
    for r, a0, w, wave, ph, c, o in strands:
        trail.append(f'<path d="{streak(r, a0, w, wave, ph)}" fill="{c}" opacity="{o}"/>')
    trail.append("</g>")
    parts += trail
    # the handle, wrapped, from the guard down to the pivot; the guard across it
    g = pt(HANDLE, A1)
    mid = pt(HANDLE / 2, A1)
    parts.append(f'<g transform="translate({mid[0]:.1f} {mid[1]:.1f}) rotate({A1 + 180})">'
                 f'<rect x="{-HANDLE/2}" y="{-hw/2}" width="{HANDLE}" height="{hw}" rx="{hw*0.3:.1f}" fill="#17141b" '
                 f'stroke="#000" stroke-width="2"/>')
    if L:
        for x in (-20, -8, 4, 16):
            parts.append(f'<polygon points="{x},{-hw/2+3} {x+6},0 {x},{hw/2-3} {x-6},0" fill="#8e3527"/>')
    elif M:
        for x in (-14, 6):
            parts.append(f'<polygon points="{x},{-hw/2+4} {x+8},0 {x},{hw/2-4} {x-8},0" fill="#8e3527"/>')
    parts.append(f'<rect x="{HANDLE/2 - 6}" y="{-hw/2-1}" width="9" height="{hw+2}" rx="3" fill="#c4974a" '
                 f'stroke="#4d3812" stroke-width="2"/></g>')
    parts.append(blade(bw, L))
    gw = 40 if L else (48 if M else 56)
    gh = 12 if L else (15 if M else 18)
    parts.append(f'<ellipse cx="{g[0]:.1f}" cy="{g[1]:.1f}" rx="{gw/2}" ry="{gh/2}" '
                 f'transform="rotate({A1 + 90} {g[0]:.1f} {g[1]:.1f})" fill="#c4974a" stroke="#4d3812" '
                 f'stroke-width="{3 if L else 4}"/>')
    # blood drops flung off the tip's path, outward; tails back along the swing and a little inward
    tip_r = HANDLE + BLADE
    def fling(r, a, size, hl=True):
        x, y = pt(r, a)
        return drop(x, y, size, a + 205, hl)
    if L:
        parts += [fling(tip_r + 20, A1 + 6, 12), fling(tip_r + 16, A1 + 16, 9.5), fling(tip_r + 12, A1 + 25, 7.5)]
    elif M:
        parts += [fling(tip_r + 18, A1 + 6, 16), fling(tip_r + 12, A1 + 21, 12)]
    else:
        parts.append(fling(tip_r + 14, A1 + 12, 21, hl=False))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            + "".join(parts) + "</svg>")


if __name__ == "__main__":
    for lv in ("large", "medium", "small"):
        with open("datapiler-%s.svg" % lv, "w", encoding="utf-8") as f:
            f.write(svg(lv))
    print("wrote 3 drawings")
