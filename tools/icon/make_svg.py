"""DataPiler's icon: an original blood-red katana in a rising slash, with blood drops. Three detail levels, so that
nothing is too small to see at 16 px. Our own drawing; no game art is used."""
import sys

def drop(cx, cy, r, rot, hl=True):
    # a teardrop whose tail points along rot (degrees; 0 = up)
    p = (f"M 0 {-2.3*r:.1f} C {0.55*r:.1f} {-1.2*r:.1f}, {r:.1f} {-0.35*r:.1f}, {r:.1f} {0.15*r:.1f} "
         f"A {r:.1f} {r:.1f} 0 1 1 {-r:.1f} {0.15*r:.1f} C {-r:.1f} {-0.35*r:.1f}, {-0.55*r:.1f} {-1.2*r:.1f}, 0 {-2.3*r:.1f} Z")
    out = f'<g transform="translate({cx} {cy}) rotate({rot})"><path d="{p}" fill="url(#drop)" stroke="#3a0008" stroke-width="{max(1.5, r*0.12):.1f}"/>'
    if hl:
        out += f'<ellipse cx="{-0.38*r:.1f}" cy="{0.0:.1f}" rx="{0.22*r:.1f}" ry="{0.34*r:.1f}" fill="#ffffff" opacity="0.55" transform="rotate(25)"/>'
    return out + "</g>"

def svg(level):
    # level: "large" (64 px and up), "medium" (32-48 px), "small" (16-24 px)
    L, M, S = level == "large", level == "medium", level == "small"
    bw = 15 if L else (21 if M else 30)            # the blade's width at its base, in the 256 grid
    hw = 18 if L else (24 if M else 30)            # the handle's width
    parts = []
    parts.append('''<defs>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#34121a"/><stop offset="1" stop-color="#0d0507"/></linearGradient>
  <linearGradient id="arc" gradientUnits="userSpaceOnUse" x1="30" y1="210" x2="214" y2="24">
    <stop offset="0" stop-color="#b3001e" stop-opacity="0"/><stop offset="0.45" stop-color="#d4122e" stop-opacity="0.55"/>
    <stop offset="1" stop-color="#ff3348" stop-opacity="0.95"/></linearGradient>
  <linearGradient id="blade" gradientUnits="userSpaceOnUse" x1="150" y1="88" x2="166" y2="104">
    <stop offset="0" stop-color="#5c0411"/><stop offset="0.5" stop-color="#b80c26"/><stop offset="1" stop-color="#e8283f"/></linearGradient>
  <radialGradient id="drop" cx="0.4" cy="0.55" r="0.75"><stop offset="0" stop-color="#ff3a4e"/><stop offset="1" stop-color="#a8001a"/></radialGradient>
</defs>''')
    parts.append('<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#tile)" stroke="#7a2232" stroke-width="5"/>')
    # the slash: a crescent bulging to the upper left, faint where it starts, bright at the tip's end
    if L:
        parts.append('<path d="M 30 206 Q 40 40 214 24 Q 84 76 30 206 Z" fill="url(#arc)"/>')
    elif M:
        parts.append('<path d="M 28 204 Q 34 34 216 22 Q 90 70 28 204 Z" fill="url(#arc)"/>')
    else:
        parts.append('<path d="M 30 196 Q 34 34 212 26 Q 98 66 30 196 Z" fill="url(#arc)"/>')
    # the blade: a katana along a gentle curve from its base (lower left) to its tip (upper right), the edge on the
    # convex, lower-right side; nearly even in width, then the point (kissaki)
    import math
    B, T = (98.0, 162.0), (222.0, 26.0)
    K = (172.0, 108.0)                                  # pulls the middle towards the edge: the curve (sori)
    def at(t):
        u = 1 - t
        return (u*u*B[0] + 2*u*t*K[0] + t*t*T[0], u*u*B[1] + 2*u*t*K[1] + t*t*T[1])
    def tangent(t):
        return (2*(1-t)*(K[0]-B[0]) + 2*t*(T[0]-K[0]), 2*(1-t)*(K[1]-B[1]) + 2*t*(T[1]-K[1]))
    edge, spine = [], []
    n = 48
    for i in range(n + 1):
        t = i / n
        w = bw * (1 - 0.18 * t) * (max(0.0, 1 - ((t - 0.86) / 0.14)) ** 0.6 if t > 0.86 else 1.0)
        x, y = at(t); dx, dy = tangent(t); ln = math.hypot(dx, dy); nx, ny = dy / ln, -dx / ln   # normal to the right
        # the edge (right of the travel) runs straight to the point; the spine curves into it
        edge.append((x - nx * w * 0.5, y - ny * w * 0.5))
        spine.append((x + nx * w * 0.5, y + ny * w * 0.5))
    pts = edge + spine[::-1]
    d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in pts) + " Z"
    parts.append(f'<path d="{d}" fill="url(#blade)" stroke="#3d0109" stroke-width="{2.2 if L else (3.2 if M else 4.5)}" '
                 f'stroke-linejoin="round"/>')
    if not S:
        hl = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in
                               [(x + (sx - x) * 0.22, y + (sy - y) * 0.22) for (x, y), (sx, sy) in zip(edge[2:44], spine[2:44])])
        parts.append(f'<path d="{hl}" fill="none" stroke="#ff7482" stroke-width="{2.2 if L else 3}" '
                     f'stroke-linecap="round" opacity="0.95"/>')
    # the handle, wrapped, down to the lower left; the guard across it
    parts.append(f'<g transform="translate(70 190) rotate(135)">'
                 f'<rect x="-32" y="{-hw/2}" width="64" height="{hw}" rx="{hw*0.3:.1f}" fill="#17141b" stroke="#000" stroke-width="2"/>')
    if L:
        for x in (-21, -9, 3, 15):
            parts.append(f'<polygon points="{x},{-hw/2+3} {x+6},0 {x},{hw/2-3} {x-6},0" fill="#8e3527"/>')
    elif M:
        for x in (-16, 4, 22):
            parts.append(f'<polygon points="{x},{-hw/2+4} {x+8},0 {x},{hw/2-4} {x-8},0" fill="#8e3527"/>')
    parts.append(f'<rect x="27" y="{-hw/2-1}" width="9" height="{hw+2}" rx="3" fill="#c4974a" stroke="#4d3812" stroke-width="2"/></g>')
    gw = 40 if L else (48 if M else 56)
    gh = 12 if L else (15 if M else 18)
    parts.append(f'<ellipse cx="95" cy="165" rx="{gw/2}" ry="{gh/2}" transform="rotate(45 95 165)" fill="#c4974a" stroke="#4d3812" stroke-width="{3 if L else 4}"/>')
    # blood drops flung down to the right, tails back towards the blade
    if L:
        parts += [drop(212, 124, 14, -45), drop(222, 176, 10, -50), drop(174, 206, 8, -30)]
    elif M:
        parts += [drop(208, 128, 19, -45), drop(206, 196, 14, -40)]
    else:
        parts += [drop(200, 150, 26, -45, hl=False)]
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            + "".join(parts) + "</svg>")

if __name__ == "__main__":
    for lv in ("large", "medium", "small"):
        open(f"datapiler-{lv}.svg", "w").write(svg(lv))
    print("ok")
