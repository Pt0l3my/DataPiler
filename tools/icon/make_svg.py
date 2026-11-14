"""DataPiler's icon (S65): an original katana with a crimson blade in a rising slash, and behind it a trail of
blood-red flame streaming off the whole blade: layered tongues, dark at their edges and bright at their cores, that
sweep back along the swing and curl at their tips. The sword is drawn to a katana's proportions. Three levels of
detail, so nothing is too small to see at 16 px. Our own drawing; no game art is used. Writes datapiler-large.svg,
-medium.svg and -small.svg in the current folder."""
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


def tongue(base, theta0, bend, length, width, hook, flen=1.0, fw=1.0):
    """One tongue of flame rooted at `base` on the blade's back edge: it leaves at angle theta0 (degrees, screen y
    down), bends by `bend` degrees on its way (negative: upward), tapers from `width` to a point, and its last part
    hooks a further `hook` degrees. flen and fw shorten and narrow it, for the inner layers of the same tongue."""
    n = 36
    pts = []
    x, y = base
    step = length * flen / n
    centre = [(x, y)]
    ang = theta0
    for i in range(1, n + 1):
        q = i / n
        ang = theta0 + bend * q ** 1.3 + (hook * ((q - 0.7) / 0.3) ** 2 if q > 0.7 else 0.0)
        ux, uy = unit(ang)
        x, y = x + ux * step, y + uy * step
        centre.append((x, y))
    left, right = [], []
    for i, (cx, cy) in enumerate(centre):
        q = i / n
        if i < n:
            dx, dy = centre[i + 1][0] - cx, centre[i + 1][1] - cy
        else:
            dx, dy = cx - centre[i - 1][0], cy - centre[i - 1][1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        w = width * fw * (1 - q) ** 1.15 * (1 + 0.25 * math.sin(math.pi * q))
        left.append((cx + nx * w / 2, cy + ny * w / 2))
        right.append((cx - nx * w / 2, cy - ny * w / 2))
    return poly(left + right[::-1])


def svg(level):
    L, M, S = level == "large", level == "medium", level == "small"
    bw = 13 if L else (19 if M else 27)                  # the blade's width at the collar
    hw = 17 if L else (23 if M else 29)                  # the handle's width
    parts = ['''<defs>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2e1117"/><stop offset="1" stop-color="#0b0406"/></linearGradient>
  <radialGradient id="drop" cx="0.4" cy="0.55" r="0.75"><stop offset="0" stop-color="#ff3a4e"/><stop offset="1" stop-color="#a8001a"/></radialGradient>
  <clipPath id="inTile"><rect x="10" y="10" width="236" height="236" rx="50"/></clipPath>
  <filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>
  <filter id="soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="1.2"/></filter>
  <filter id="fire1" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="0.018 0.055" numOctaves="2" seed="7" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="26" xChannelSelector="R" yChannelSelector="G"/></filter>
  <filter id="fire2" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="0.022 0.07" numOctaves="2" seed="21" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="18" xChannelSelector="R" yChannelSelector="G"/></filter>
  <filter id="fire3" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="0.03 0.09" numOctaves="2" seed="42" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="11" xChannelSelector="R" yChannelSelector="G"/></filter>
</defs>''',
             '<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#tile)" stroke="#7a2232" stroke-width="5"/>']
    edge, back, center, yokote = blade_outline(bw)
    # the flame trail: one body of blood-red fire along the blade's back, breaking into tongues that stream back
    # along the swing and rise, longest towards the point where the blade moves fastest, hooked at their tips; each
    # a dark outer flame, a red body and a bright core; a soft glow beneath
    if L:
        # (where on the blade, leaving angle, bend, length, width, hook)
        tongues = ((0.16, 78, -70, 52, 34, -45), (0.29, 74, -84, 74, 40, 50), (0.42, 70, -96, 92, 44, -55),
                   (0.55, 64, -104, 104, 46, 60), (0.67, 56, -108, 108, 46, -60), (0.78, 46, -104, 100, 42, 55),
                   (0.88, 34, -96, 84, 36, -50), (0.96, 22, -84, 62, 28, 45), (0.48, 86, -70, 70, 28, 65),
                   (0.73, 76, -86, 82, 26, -60))
    elif M:
        tongues = ((0.22, 76, -80, 66, 46, -45), (0.45, 68, -98, 96, 54, 55), (0.68, 56, -106, 108, 54, -60),
                   (0.90, 34, -94, 82, 44, 55))
    else:
        tongues = ((0.34, 72, -88, 84, 66, 0), (0.72, 50, -100, 104, 66, 0))
    layers = ((("#5a000f", 1.0, 1.0, 1.0), ("#bf0d2b", 0.82, 0.66, 1.0), ("#ff2f46", 0.6, 0.36, 1.0),
               ("#ff9aa6", 0.38, 0.12, 0.8)) if L else
              (("#5e0010", 1.0, 1.0, 1.0), ("#cf1230", 0.8, 0.62, 1.0), ("#ff3a50", 0.55, 0.3, 1.0)) if M else
              (("#6a0012", 1.0, 1.0, 1.0), ("#e3183a", 0.75, 0.55, 1.0)))
    def root(sk):
        i = round(sk * (len(back) - 1))
        x, y = back[min(i, len(back) - 1)]
        cx, cy = center[min(i, len(center) - 1)][:2]
        return x + (cx - x) * 0.4, y + (cy - y) * 0.4       # just inside the back, so the blade covers the root
    fl = ['<g clip-path="url(#inTile)">']
    glow = "".join(f'<path d="{tongue(root(sk), t0_, bd, ln, wd, hk)}" fill="#ff1838"/>'
                   for sk, t0_, bd, ln, wd, hk in tongues)
    fl.append(f'<g filter="url(#glow)" opacity="{0.55 if L else 0.4}">' + glow + "</g>")
    # each layer as one shape, its edges broken by its own noise (large and medium sizes), so the flames flicker;
    # the noise runs along the flow (turned with it), so the tongues stay long
    fires = ("fire1", "fire2", "fire3", "fire3")
    for k, (col, flen, fw, op) in enumerate(layers):
        shapes = "".join(f'<path d="{tongue(root(sk), t0_, bd, ln, wd, hk, flen, fw)}"/>'
                         for sk, t0_, bd, ln, wd, hk in tongues)
        if S:
            fl.append(f'<g fill="{col}" opacity="{op}">{shapes}</g>')
        else:
            fl.append(f'<g transform="rotate(-25 150 120)"><g filter="url(#{fires[k]})"><g transform="rotate(25 150 120)" '
                      f'fill="{col}" opacity="{op}">{shapes}</g></g></g>')
    fl.append("</g>")
    parts += fl
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
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            + "".join(parts) + "</svg>")


if __name__ == "__main__":
    for lv in ("large", "medium", "small"):
        with open("datapiler-%s.svg" % lv, "w", encoding="utf-8") as f:
            f.write(svg(lv))
    print("wrote 3 drawings")
