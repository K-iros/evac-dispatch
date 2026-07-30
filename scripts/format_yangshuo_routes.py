# -*- coding: utf-8 -*-
"""把 yangshuo_demo_routes.json 简化（RDP）并输出 py/ts 字面量片段。"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def rdp(points, eps):
    if len(points) < 3:
        return points

    def perp(p, a, b):
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            return math.hypot(p[0] - ax, p[1] - ay)
        t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))

    dmax, idx = 0, 0
    for i in range(1, len(points) - 1):
        d = perp(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(points[: idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def main():
    with open(os.path.join(HERE, "yangshuo_demo_routes.json"), encoding="utf-8") as f:
        data = json.load(f)

    eps = 0.00008  # 约 9 米
    lines = []
    for a in data["assignments"]:
        pts = [tuple(p) for p in a["coordinates"]]
        simp = rdp(pts, eps)
        lines.append("## %s -> %s -> %s (%s)  %d -> %d 点  %.3f km / %.1f min"
                     % (a["helper"], a["evacuee"], a["shelter"], a["type"],
                        len(pts), len(simp), a["distance_km"], a["duration_min"]))
        py = ",\n".join("                (%.5f, %.5f)" % p for p in simp)
        ts = ",\n".join("          [%.5f, %.5f]" % p for p in simp)
        lines.append("--- python ---\n%s" % py)
        lines.append("--- ts/js ---\n%s\n" % ts)

    out = "\n".join(lines)
    with open(os.path.join(HERE, "yangshuo_route_literals.txt"), "w",
              encoding="utf-8") as f:
        f.write(out)
    print(out)


if __name__ == "__main__":
    main()
