"""DataPiler's icon (S65): an original katana with a crimson blade, in a rising slash, wrapped and trailed by
blood-red flame that breaks up into a spray of blood towards its ends. The sword is drawn to a katana's plain
proportions: a slender curved blade, a collar, a round guard of dark iron edged in gold, and a handle wrapped in black cord over deep crimson diamonds.
The flames are layered dark to bright, their edges broken so they flicker; the spray leaves the flames' tips along
their flow, densest near them and thinning out, each drop drawn out by the swing. Three levels of detail, so nothing
is too small to see at 16 px. Our own drawing; no game art is used. Writes datapiler-large.svg, -medium.svg and
-small.svg in the current folder."""
import math
import random

K = (36.0, 222.0)          # the end of the handle (kashira), where the swing turns
A1 = -49.0                 # the sword's angle now (degrees; screen y points down): the point up and to the right
A0 = -35.0                 # its angle where the trail begins
HANDLE, GUARD, COLLAR, BLADE = 64.0, 6.0, 9.0, 192.0
SORI = 9.0                 # how far the blade's middle bows towards its edge
WAVES = (7.0, 3.2)         # the blade's even waves: how many along it, and how far each swings (set per level)


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
    n = 160
    yokote = 0.9
    waves = WAVES[0]
    amp = WAVES[1]
    for i in range(n + 1):
        s = i / n
        w = bw * (1 - 0.3 * s)
        e, b = w / 2, w / 2
        if s > yokote:                                   # the point: the edge sweeps up to meet the straight back
            f = (s - yokote) / (1 - yokote)
            e = w / 2 * math.sqrt(max(0.0, 1 - f ** 1.6))
            b = w / 2 * (1 - f ** 3)
        x, y = at(s); px, py = normal(s)
        fade = min(1.0, s / 0.08) * (min(1.0, (1 - s) / 0.14) if s > 0.86 else 1.0)
        wv = amp * math.sin(2 * math.pi * waves * s) * fade      # an even wave, both edges together
        x, y = x + px * wv, y + py * wv
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


def tongue_tip(base, theta0, bend, length, hook):
    """Where a tongue (as tongue() draws it) ends, and the heading it ends on."""
    n = 36
    x, y = base
    step = length / n
    ang = theta0
    for i in range(1, n + 1):
        q = i / n
        ang = theta0 + bend * q ** 1.3 + (hook * ((q - 0.7) / 0.3) ** 2 if q > 0.7 else 0.0)
        ux, uy = unit(ang)
        x, y = x + ux * step, y + uy * step
    return (x, y), ang


def spray(tips, level):
    """Blood flung off the flames' tips: drops along each tip's heading, densest near it and thinning out, smaller
    and fainter the further they fly, each drawn out along its flight. Seeded, so the drawing is the same each time."""
    L, M = level == "large", level == "medium"
    rnd = random.Random(1897)
    per = 9 if L else (5 if M else 2)
    colours = ("#ff2a40", "#e0162f", "#b10c24", "#7c0617")
    out = []
    for (tx, ty), ang in tips:
        for _ in range(per):
            d = rnd.random() ** 1.6 * (78 if L else (64 if M else 40))
            spread = rnd.gauss(0, 6 + 0.35 * d)
            heading = ang + rnd.uniform(-14, 10)
            ux, uy = unit(heading)
            px, py = -uy, ux
            x, y = tx + ux * (d + 4) + px * spread, ty + uy * (d + 4) + py * spread
            size = (5.2 if L else (7.5 if M else 10.0)) * (1 - d / (90 if L else 75)) * rnd.uniform(0.55, 1.0)
            size = max(size, 1.4 if L else (2.4 if M else 4.0))
            col = colours[min(3, int(d / (24 if L else 20)))] if rnd.random() > 0.12 else "#ff7a88"
            out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{size * (1.9 if L else 1.6):.1f}" ry="{size:.1f}" '
                       f'transform="rotate({heading:.0f} {x:.1f} {y:.1f})" fill="{col}" '
                       f'opacity="{max(0.45, 1 - d / 120):.2f}"/>')
            if L and rnd.random() < 0.35:                  # a few fine specks around the bigger drops
                sx, sy = x + rnd.gauss(0, 7), y + rnd.gauss(0, 7)
                out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{rnd.uniform(0.8, 1.6):.1f}" fill="#d4122e" '
                           f'opacity="0.8"/>')
    return out


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
    global WAVES
    WAVES = (0.0, 0.0)                                  # a plain katana curve under the flames
    edge, back, center, yokote = blade_outline(bw)
    # the flame trail: one body of blood-red fire along the blade's back, breaking into tongues that stream back
    # along the swing and rise, longest towards the point where the blade moves fastest, hooked at their tips; each
    # a dark outer flame, a red body and a bright core; a soft glow beneath
    if L:
        # (where on the blade, leaving angle, bend, length, width, hook) - uneven on purpose, as fire is
        tongues = ((0.15, 80, -64, 44, 30, -40), (0.27, 70, -88, 78, 44, 55), (0.41, 76, -104, 98, 40, -45),
                   (0.52, 58, -96, 82, 50, 65), (0.64, 66, -118, 116, 46, -70), (0.77, 44, -100, 96, 40, 50),
                   (0.86, 38, -84, 70, 30, -60), (0.95, 20, -90, 56, 24, 45), (0.34, 92, -60, 58, 18, 80),
                   (0.70, 84, -70, 74, 16, -75), (0.58, 30, -120, 104, 14, 70))
    elif M:
        tongues = ((0.22, 78, -78, 62, 46, -45), (0.44, 64, -102, 96, 56, 55), (0.66, 70, -114, 112, 50, -65),
                   (0.88, 36, -92, 76, 40, 55))
    else:
        tongues = ((0.32, 72, -88, 80, 66, 0), (0.70, 54, -104, 104, 66, 0))
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
    tips = [tongue_tip(root(sk), t0_, bd, ln, hk) for sk, t0_, bd, ln, wd, hk in tongues]
    fl += spray(tips, level)
    fl.append("</g>")
    parts += fl
    # the handle: dark cord over light diamonds, a collar (fuchi) at the guard and a cap (kashira) at the end
    hm = along(HANDLE / 2)
    parts.append(f'<g transform="translate({hm[0]:.1f} {hm[1]:.1f}) rotate({A1})">')
    parts.append(f'<rect x="{-HANDLE/2}" y="{-hw/2}" width="{HANDLE}" height="{hw}" rx="{hw*0.25:.1f}" fill="#0c0a0d" '
                 f'stroke="#000" stroke-width="2"/>')
    if not S:
        count = 5 if L else 3
        span = HANDLE - 18
        for d in range(count):
            x = -HANDLE / 2 + 10 + span * (d + 0.5) / count
            a, b = (span / count) * 0.36, hw * 0.3
            parts.append(f'<polygon points="{x - a:.1f},0 {x:.1f},{-b:.1f} {x + a:.1f},0 {x:.1f},{b:.1f}" fill="#c8162f" '
                         f'stroke="#5e0712" stroke-width="1"/>')
    else:
        parts.append(f'<line x1="{-HANDLE/2 + 10}" y1="0" x2="{HANDLE/2 - 8}" y2="0" stroke="#d81a36" stroke-width="6" '
                     f'stroke-dasharray="8 7"/>')
    parts.append(f'<rect x="{-HANDLE/2 - 3}" y="{-hw/2 - 1}" width="8" height="{hw + 2}" rx="3" fill="#2a2228" '
                 f'stroke="#c49a4a" stroke-width="2"/>')
    parts.append(f'<rect x="{HANDLE/2 - 6}" y="{-hw/2 - 1}" width="7" height="{hw + 2}" rx="2" fill="#2a2228" '
                 f'stroke="#c49a4a" stroke-width="2"/>')
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
    # the blade wrapped in fire: tongues rising off its edge side and leaning back along the swing, a red body over
    # the blade's own outline, and a bright core along its length; edges broken by noise, so it all flickers
    def edge_root(sk):
        i = round(sk * (len(edge) - 1))
        x, y = edge[min(i, len(edge) - 1)]
        cx, cy = center[min(i, len(center) - 1)][:2]
        return x + (cx - x) * 0.3, y + (cy - y) * 0.3
    if L:
        wrap = ((0.08, -118, 40, 30, 20, 30), (0.2, -112, 46, 40, 24, -35), (0.33, -104, 52, 44, 24, 40),
                (0.46, -98, 54, 46, 24, -40), (0.59, -90, 52, 44, 22, 40), (0.72, -84, 48, 40, 20, -35),
                (0.84, -78, 44, 34, 18, 35), (0.94, -70, 40, 26, 14, -30), (0.27, -126, 30, 26, 12, 50),
                (0.53, -122, 28, 28, 12, -50), (0.78, -112, 26, 24, 10, 45))
    elif M:
        wrap = ((0.12, -114, 44, 34, 28, 30), (0.36, -104, 52, 44, 30, -35), (0.6, -92, 52, 44, 28, 40),
                (0.84, -80, 46, 36, 22, -35))
    else:
        wrap = ((0.25, -108, 40, 38, 36, 0), (0.7, -88, 42, 40, 34, 0))
    wl = ['<g clip-path="url(#inTile)">']
    wl.append('<g filter="url(#glow)" opacity="0.55">' + "".join(
        f'<path d="{tongue(edge_root(sk), t0_, bd, ln, wd, hk)}" fill="#ff1838"/>' for sk, t0_, bd, ln, wd, hk in wrap)
        + f'<path d="{poly(edge + back[::-1])}" fill="#ff1838" transform="translate(0 0)"/></g>')
    fires = ("fire1", "fire2", "fire3", "fire3")
    for k, (col, flen, fw, op) in enumerate(layers):
        shapes = "".join(f'<path d="{tongue(edge_root(sk), t0_, bd, ln, wd, hk, flen, fw)}"/>'
                         for sk, t0_, bd, ln, wd, hk in wrap)
        if k == 0:
            # the dark outer flame also covers the blade a little wider than the blade itself
            wide = [(x + px * w * 0.95, y + py * w * 0.95) for x, y, px, py, w, s in center] + \
                   [(x - px * w * 0.95, y - py * w * 0.95) for x, y, px, py, w, s in center][::-1]
            shapes += f'<path d="{poly(wide)}"/>'
        if k == 1:
            shapes += f'<path d="{poly(edge + back[::-1])}"/>'
        if S:
            wl.append(f'<g fill="{col}" opacity="{op}">{shapes}</g>')
        else:
            wl.append(f'<g transform="rotate(-25 150 120)"><g filter="url(#{fires[k]})"><g transform="rotate(25 150 120)" '
                      f'fill="{col}" opacity="{op}">{shapes}</g></g></g>')
    # the blade over the flames: a crimson katana, brighter along its edge, darker along its back, with a pale
    # temper line and the line across the point at the largest size
    wl.append("</g>")
    parts += wl
    wl = ['<g>']
    wl.append(f'<path d="{poly(edge + back[::-1])}" fill="#b5102a" stroke="#1c0004" stroke-width="{2.4 if L else 3.5}" '
              f'stroke-linejoin="round"/>')
    nb = round(yokote * (len(center) - 1))
    backband = [(x - px * w * 0.5, y - py * w * 0.5) for x, y, px, py, w, s in center]
    ridge = [(x - px * w * 0.05, y - py * w * 0.05) for x, y, px, py, w, s in center]
    wl.append(f'<path d="{poly(backband + ridge[::-1])}" fill="#640716" opacity="0.9"/>')
    edgeband = edge[:nb] + [(x + px * w * 0.16, y + py * w * 0.16) for x, y, px, py, w, s in center[:nb]][::-1]
    wl.append(f'<path d="{poly(edgeband)}" fill="#ff4a5e"/>')
    if L:
        hamon = [(x + px * w * (0.16 + 0.06 * math.sin(s * 44)), y + py * w * (0.16 + 0.06 * math.sin(s * 44)))
                 for x, y, px, py, w, s in center[:nb]]
        wl.append('<path d="M ' + " L ".join(f"{x:.1f} {y:.1f}" for x, y in hamon) +
                  '" fill="none" stroke="#ffc7cd" stroke-width="1.1" opacity="0.8"/>')
        yx, yy, ypx, ypy, yw, _ = center[nb]
        wl.append(f'<line x1="{yx + ypx * yw * 0.5:.1f}" y1="{yy + ypy * yw * 0.5:.1f}" x2="{yx - ypx * yw * 0.5:.1f}" '
                  f'y2="{yy - ypy * yw * 0.5:.1f}" stroke="#ffc7cd" stroke-width="1.2" opacity="0.85"/>')
    wl.append("</g>")
    parts += wl
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            + "".join(parts) + "</svg>")


if __name__ == "__main__":
    for lv in ("large", "medium", "small"):
        with open("datapiler-%s.svg" % lv, "w", encoding="utf-8") as f:
            f.write(svg(lv))
    print("wrote 3 drawings")
