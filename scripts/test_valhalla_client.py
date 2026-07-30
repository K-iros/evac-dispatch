# -*- coding: utf-8 -*-
"""联调 backend/app/core/routing.py 的 Valhalla 客户端（阳朔真实坐标）。"""
import asyncio
import sys

sys.path.insert(0, r"d:\File\waitan\backend")

from app.core.routing import (  # noqa: E402
    get_matrix,
    get_route,
    score_blind_route,
)

H2 = (110.48954, 24.77977)   # 李网格（叠翠路）
E2 = (110.49275, 24.78125)   # 陈先生（滨江路，视障）
SH1 = (110.48455, 24.77903)  # 阳朔公园应急避难点


async def main():
    r = await get_route("blind", [H2, E2, SH1])
    print("route(blind): %.0f m / %.0f s / %d 点 / %d legs" % (
        r["distance_m"], r["duration_s"], len(r["coordinates"]), len(r["legs"])))
    print("  首点 %s 尾点 %s" % (r["coordinates"][0], r["coordinates"][-1]))
    print("  盲人路线转折评分: %.1f" % score_blind_route(r["coordinates"]))

    m = await get_matrix("wheelchair", [H2, SH1], [E2])
    print("matrix(wheelchair) h2/sh1 -> e2:", m)


if __name__ == "__main__":
    asyncio.run(main())
