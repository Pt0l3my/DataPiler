"""DataPiler's icon (S65): an original katana with a blood-red blade in a rising slash, its trail streaming off the
whole blade, with blood drops. Drawn to a katana's proportions: a slender, evenly curved blade about three times the
handle, a point (kissaki) whose edge sweeps up to meet the back, a temper line along the edge, a collar (habaki), a
round guard (tsuba), and a handle wrapped in dark cord over light diamonds. Three levels of detail, so nothing is too
small to see at 16 px. Our own drawing; no game art is used. Writes datapiler-large.svg, -medium.svg and -small.svg
in the current folder."""
import math

K = (36.0, 222.0)          # the end of the handle (kashira), where the swing turns
A1 = -49.0                 # the sword's angle now (degrees; screen y points down): the point up and to the right
A0 = -35.0                 # its angle where the trail begins
HANDLE, GUARD, COLLAR, BLADE = 64.0, 6.0, 9.0, 192.0
SORI = 9.0                 # how far the blade's middle bows towards its edge


def unit(a):
    return math.cos(math.radians(a)), math.sin(math.radians(a))


def along(d, a=A1):
    ux, uy = unit(a)
    return K[0] + d * ux, K[1] + d * uy


def rot_pt(p, da):
    """p turned by da degrees around K."""
    c, s = math.cos(math.radians(da)), math.sin(math.radians(da))
    x, y = p[0] - K[0], p[1] - K[1]
    return K[0] + x * c - y * s, K[1] + x * s + y * c


def poly(pts):
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"


def blade_outline(bw):
    """The blade's edge and back, from the collar to the point. The edge is on the upper left (it leads the swing)."""
    b0 = HANDLE + GUARD + COLLAR
    g = along(b0)
    t = along(b0 + BLADE)
    ux, uy = unit(A1)
    nx, ny = uy, -ux                                     # the normal towards the upper left: the edge's side
    mid = ((g[0] + t[0]) / 2 + nx * SORI, (g[1] + t[1]) / 2 + ny * SORI)
    def at(s):
        u = 1 - s
        return u * u * g[0] + 2 * u * s * mid[0] + s * s * t[0], u * u * g[1] + 2 * u * s * mid[1] + s * s * t[1]
    def normal(s):
        dx = 2 * (1 - s) * (mid[0] - g[0]) + 2 * s * (t[0] - mid[0])
        dy = 2 * (1 - s) * (mid[1] - g[1]) + 2 * s * (t[1] - mid[1])
        ln = math.hypot(dx, dy)
        return dy / ln, -dx / ln
    edge, back, center = [], [], []
    n = 80
    yokote = 0.9
    for i in range(n + 1):
        s = i / n
        w = bw * (1 - 0.3 * s)
        e, b = w / 2, w / 2
        if s > yokote:                                   # the point: the edge sweeps up to meet the straight back
            f = (s - yokote) / (1 - yokote)
            e = w / 2 * math.sqrt(max(0.0, 1 - f ** 1.6))
            b = w / 2 * (1 - f ** 3)
        x, y = at(s); px, py = normal(s)
        edge.append((x + px * e, y + py * e))
        back.append((x - px * b, y - py * b))
        center.append((x, y, px, py, w, s))
    return edge, back, center, yokote


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


def svg(level):
    L, M, S = level == "large", level == "medium", level == "small"
    bw = 13 if L else (19 if M else 27)                  # the blade's width at the collar
    hw = 17 if L else (23 if M else 29)                  # the handle's width
    parts = ['''<defs>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2e1117"/><stop offset="1" stop-color="#0b0406"/></linearGradient>
  <radialGradient id="drop" cx="0.4" cy="0.55" r="0.75"><stop offset="0" stop-color="#ff3a4e"/><stop offset="1" stop-color="#a8001a"/></radialGradient>
  <clipPath id="inTile"><rect x="10" y="10" width="236" height="236" rx="50"/></clipPath>
</defs>''',
             '<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#tile)" stroke="#7a2232" stroke-width="5"/>']
    edge, back, center, yokote = blade_outline(bw)
    # the trail: the blade's own shape at earlier moments of the swing, faint far back and close behind it deeper,
    # so it streams off the whole blade and keeps the blade's curve
    trail = ['<g clip-path="url(#inTile)">']
    n = 16 if L else (10 if M else 6)
    for k in range(n):
        f = k / n                                        # 0 where the trail begins, near 1 just behind the blade
        da = (A0 - A1) * (1 - f)
        ghost = [rot_pt(p, da) for p in edge] + [rot_pt(p, da) for p in back[::-1]]
        # a ghost blade, widened backwards (towards where it came from) so the ghosts overlap into one band
        sweep = [rot_pt(p, da + (A0 - A1) / n * 1.15) for p in back]
        band = [rot_pt(p, da) for p in edge] + sweep[::-1]
        col = "#%02x%02x%02x" % tuple(round(a + (b - a) * f) for a, b in zip((96, 0, 18), (214, 24, 50)))
        op = (0.02 + 0.11 * f * f) if L else ((0.03 + 0.13 * f * f) if M else (0.05 + 0.16 * f * f))
        trail.append(f'<path d="{poly(band)}" fill="{col}" opacity="{op:.3f}"/>')
    # strands: lines of blood left by points along the edge, tapering away from the blade
    if not S:
        picks = (0.985, 0.9, 0.78, 0.66, 0.54, 0.42, 0.3) if L else (0.96, 0.72, 0.48)
        for j, s in enumerate(picks):
            i = round(s * (len(edge) - 1))
            p = edge[i]
            r = math.hypot(p[0] - K[0], p[1] - K[1])
            a_end = math.degrees(math.atan2(p[1] - K[1], p[0] - K[0]))
            a_start = a_end + (A0 - A1) * (1.0 - 0.09 * j) * (1.0 if j % 2 == 0 else 0.8)
            w = (7.0 if L else 10.0) * (1 - 0.08 * j)
            out_, in_ = [], []
            for m in range(25):
                q = m / 24
                a = a_start + (a_end - a_start) * q
                half = w * 0.5 * q ** 0.85
                wave = (2.5 if L else 3.0) * math.sin(j * 1.7 + q * 7.0) * (1 - q)
                ux, uy = unit(a)
                out_.append((K[0] + (r + wave + half) * ux, K[1] + (r + wave + half) * uy))
                in_.append((K[0] + (r + wave - half) * ux, K[1] + (r + wave - half) * uy))
            trail.append(f'<path d="{poly(out_ + in_[::-1])}" fill="{"#ff4a5c" if j % 2 == 0 else "#d81a36"}" '
                         f'opacity="{0.95 - 0.06 * j:.2f}"/>')
    trail.append("</g>")
    parts += trail
    # the handle: dark cord over light diamonds, a collar (fuchi) at the guard and a cap (kashira) at the end
    hm = along(HANDLE / 2)
    parts.append(f'<g transform="translate({hm[0]:.1f} {hm[1]:.1f}) rotate({A1})">')
    parts.append(f'<rect x="{-HANDLE/2}" y="{-hw/2}" width="{HANDLE}" height="{hw}" rx="{hw*0.25:.1f}" fill="#141117" '
                 f'stroke="#000" stroke-width="2"/>')
    if not S:
        count = 5 if L else 3
        span = HANDLE - 18
        for d in range(count):
            x = -HANDLE / 2 + 10 + span * (d + 0.5) / count
            a, b = (span / count) * 0.36, hw * 0.3
            parts.append(f'<polygon points="{x - a:.1f},0 {x:.1f},{-b:.1f} {x + a:.1f},0 {x:.1f},{b:.1f}" fill="#e9dcc0"/>')
    else:
        parts.append(f'<line x1="{-HANDLE/2 + 10}" y1="0" x2="{HANDLE/2 - 8}" y2="0" stroke="#e9dcc0" stroke-width="5" '
                     f'stroke-dasharray="8 7"/>')
    parts.append(f'<rect x="{-HANDLE/2 - 3}" y="{-hw/2 - 1}" width="8" height="{hw + 2}" rx="3" fill="#2a2228" '
                 f'stroke="#c49a4a" stroke-width="2"/>')
    parts.append(f'<rect x="{HANDLE/2 - 6}" y="{-hw/2 - 1}" width="7" height="{hw + 2}" rx="2" fill="#c49a4a" '
                 f'stroke="#4d3812" stroke-width="1.5"/>')
    parts.append("</g>")
    # the guard (tsuba), round and seen at a slant; the collar (habaki) on the blade
    gc = along(HANDLE + GUARD / 2)
    gr = 21 if L else (25 if M else 28)
    parts.append(f'<ellipse cx="{gc[0]:.1f}" cy="{gc[1]:.1f}" rx="{gr}" ry="{gr*0.32:.1f}" transform="rotate({A1 + 90} '
                 f'{gc[0]:.1f} {gc[1]:.1f})" fill="#231c20" stroke="#c49a4a" stroke-width="{2.5 if L else 4}"/>')
    hb = along(HANDLE + GUARD + COLLAR / 2)
    parts.append(f'<g transform="translate({hb[0]:.1f} {hb[1]:.1f}) rotate({A1})"><rect x="{-COLLAR/2 - 1}" '
                 f'y="{-bw/2 - 2}" width="{COLLAR + 2}" height="{bw + 4}" rx="2" fill="#d8ad55" stroke="#5a4114" '
                 f'stroke-width="1.5"/></g>')
    # the blade: crimson, darker along its back, brighter at the edge, with a wavy temper line (hamon) near the edge,
    # the ridge (shinogi) and the line across the point (yokote)
    outline = edge + back[::-1]
    parts.append(f'<path d="{poly(outline)}" fill="#a80f26" stroke="#1c0004" stroke-width="{2.4 if L else 3.5}" '
                 f'stroke-linejoin="round"/>')
    backband = [(x - px * w * 0.5, y - py * w * 0.5) for x, y, px, py, w, s in center]
    ridge = [(x - px * w * 0.05, y - py * w * 0.05) for x, y, px, py, w, s in center]
    nb = round(yokote * (len(center) - 1))
    parts.append(f'<path d="{poly(backband[:nb] + ridge[:nb][::-1])}" fill="#5e0612" opacity="0.85"/>')
    if not S:
        hamon = []
        for i, (x, y, px, py, w, s) in enumerate(center[:nb]):
            off = w * (0.16 + (0.07 if L else 0.05) * math.sin(s * (44 if L else 26)))
            hamon.append((x + px * off, y + py * off))
        edgeband = edge[:nb] + hamon[::-1]
        parts.append(f'<path d="{poly(edgeband)}" fill="#ff5c6c" opacity="0.95"/>')
        if L:
            parts.append('<path d="M ' + " L ".join(f"{x:.1f} {y:.1f}" for x, y in hamon) +
                         '" fill="none" stroke="#ffd0d5" stroke-width="1.2" opacity="0.8"/>')
            yx, yy, ypx, ypy, yw, _ = center[nb]
            parts.append(f'<line x1="{yx + ypx * yw * 0.5:.1f}" y1="{yy + ypy * yw * 0.5:.1f}" x2="{yx - ypx * yw * 0.5:.1f}" '
                         f'y2="{yy - ypy * yw * 0.5:.1f}" stroke="#ffd0d5" stroke-width="1.3" opacity="0.85"/>')
    else:
        parts.append(f'<path d="{poly(edge[:nb] + [(x + px * w * 0.12, y + py * w * 0.12) for x, y, px, py, w, s in center[:nb]][::-1])}" '
                     f'fill="#ff5c6c"/>')
    if S:
        # at 16 to 24 px the trail is one strand, wide enough to see
        i = round(0.93 * (len(edge) - 1))
        p = edge[i]
        r = math.hypot(p[0] - K[0], p[1] - K[1])
        a_end = math.degrees(math.atan2(p[1] - K[1], p[0] - K[0]))
        out_, in_ = [], []
        for m in range(25):
            q = m / 24
            a = a_end + (A0 - A1) * (1 - q)
            half = 7.0 * q ** 1.2
            ux_, uy_ = unit(a)
            out_.append((K[0] + (r + half) * ux_, K[1] + (r + half) * uy_))
            in_.append((K[0] + (r - half) * ux_, K[1] + (r - half) * uy_))
        parts.insert(3, f'<path clip-path="url(#inTile)" d="{poly(out_ + in_[::-1])}" fill="#ff4a5c" opacity="0.95"/>')
    # blood drops flung forwards off the edge, into the open corner; tails back towards the blade
    ux, uy = unit(A1)
    nx, ny = uy, -ux
    def fling(d, off, size, hl=True):
        x, y = along(d)
        return drop(x + nx * off, y + ny * off, size, A1 + 180, hl)     # tail back towards the blade
    if L:
        parts += [fling(196, 40, 11), fling(148, 46, 9), fling(104, 40, 7)]
    elif M:
        parts += [fling(186, 42, 15), fling(124, 46, 11)]
    else:
        parts.append(fling(158, 48, 19, hl=False))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            + "".join(parts) + "</svg>")


if __name__ == "__main__":
    for lv in ("large", "medium", "small"):
        with open("datapiler-%s.svg" % lv, "w", encoding="utf-8") as f:
            f.write(svg(lv))
    print("wrote 3 drawings")
