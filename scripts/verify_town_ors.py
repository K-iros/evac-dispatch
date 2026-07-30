# -*- coding: utf-8 -*-
"""PROJECT_CONTEXT 第十节：候选城镇 ORS 公共 API 轮椅路径试跑。

用法：
    python scripts/verify_town_ors.py <ORS_API_KEY>
    或设置环境变量 ORS_API_KEY 后直接运行

每个候选城镇试跑 3 条起终点对（起终点自动从 Overpass 拉取真实道路节点，
避免手拍坐标离路网太远造成假失败），
分别用 wheelchair 与 foot-walking 两个 profile 请求 directions，
记录：是否出路径 / 距离 / 耗时 / 报错信息。
结果输出到控制台 + scripts/town_ors_result.json。
"""
import json
import http.client
import math
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ORS_HOST = "api.openrouteservice.org"
ORS_PATH = "/v2/directions/{profile}/geojson"
PROFILES = ["wheelchair", "foot-walking"]

# 本地 DNS 可能被污染（解析到 Facebook/Twitter 段 IP），用 DoH 拿真实 IP 后按 IP 直连（保留 SNI）
DOH_ENDPOINTS = [
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
    "https://dns.google/resolve?name={host}&type=A",
]
# DoH 全部失效时的兼底：HeiGIT（海德堡大学）官方段
ORS_FALLBACK_IP = "129.206.5.53"


def resolve_via_doh(host: str) -> str:
    for tpl in DOH_ENDPOINTS:
        try:
            req = urllib.request.Request(
                tpl.format(host=host), headers={"accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            for ans in data.get("Answer", []):
                ip = ans.get("data", "")
                # 排除已知污染段（Facebook 31.13.*、Twitter 104.244.*）
                if ip and not ip.startswith(("31.13.", "104.244.")):
                    return ip
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] DoH {tpl.split('/')[2]} 失败: {e}")
    return ORS_FALLBACK_IP

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# bbox = (south, west, north, east)，与 verify_town_osm.py 一致
CANDIDATES = {
    "贵州榕江县城": (25.90, 108.48, 25.97, 108.56),
    "重庆磁器口/沙坪坝片区": (29.54, 106.40, 29.62, 106.50),
    "广西阳朔县城": (24.74, 110.45, 24.81, 110.53),
}


def fetch_road_nodes(bbox: tuple) -> list:
    """拉取 bbox 内可步行道路的几何点（排除 motorway/trunk）。"""
    bbox_str = ",".join(str(v) for v in bbox)
    query = (
        f'[out:json][timeout:120];'
        f'way["highway"~"^(residential|tertiary|secondary|primary|unclassified|living_street|footway)$"]({bbox_str});'
        f'out geom 200;'
    )
    data = ("data=" + urllib.parse.quote(query)).encode()
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint, data=data, headers={
                "User-Agent": "waitan-evac-demo-town-verify/1.0"})
            with urllib.request.urlopen(req, timeout=150) as resp:
                result = json.loads(resp.read().decode())
            pts = []
            for el in result.get("elements", []):
                for g in el.get("geometry", [])[:2]:  # 每条 way 取头两个点避免堆积
                    pts.append((g["lon"], g["lat"]))
            if pts:
                return pts
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"    [warn] {endpoint} 失败: {e}")
            time.sleep(3)
    raise RuntimeError(f"拉取道路节点失败: {last_err}")


def dist_m(a, b) -> float:
    dx = (a[0] - b[0]) * 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110540
    return math.hypot(dx, dy)


def pick_pairs(pts: list, n: int = 3) -> list:
    """从道路点中选 n 对相距 800-2500m 的起终点，尽量分散。"""
    pairs = []
    used = set()
    step = max(1, len(pts) // (n * 7))
    for i in range(0, len(pts), step):
        if len(pairs) >= n:
            break
        if i in used:
            continue
        for j in range(i + 1, len(pts)):
            if j in used:
                continue
            d = dist_m(pts[i], pts[j])
            if 800 <= d <= 2500:
                pairs.append((f"试跑{len(pairs) + 1} (~{int(d)}m)", list(pts[i]), list(pts[j])))
                used.update((i, j))
                break
    return pairs


def try_route(api_key: str, ors_ip: str, profile: str, start, end) -> dict:
    body = json.dumps({"coordinates": [start, end]})
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/geo+json",
        "Host": ORS_HOST,
        "User-Agent": "waitan-evac-demo-town-verify/1.0",
    }
    conn = None
    try:
        ctx = ssl.create_default_context()
        raw = socket.create_connection((ors_ip, 443), timeout=60)
        ssock = ctx.wrap_socket(raw, server_hostname=ORS_HOST)
        conn = http.client.HTTPSConnection(ORS_HOST, 443, timeout=60)
        conn.sock = ssock
        conn.request("POST", ORS_PATH.format(profile=profile), body=body, headers=headers)
        resp = conn.getresponse()
        payload = resp.read().decode()
        if resp.status != 200:
            try:
                detail = json.loads(payload).get("error", {})
                msg = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
            except Exception:  # noqa: BLE001
                msg = payload[:200]
            return {"ok": False, "error": f"HTTP {resp.status}: {msg}"}
        geo = json.loads(payload)
        feat = geo["features"][0]
        summary = feat["properties"]["summary"]
        return {
            "ok": True,
            "distance_m": round(summary.get("distance", 0), 1),
            "duration_min": round(summary.get("duration", 0) / 60, 1),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ORS_API_KEY", "")
    if not api_key:
        print("用法: python verify_town_ors.py <ORS_API_KEY>（或设 ORS_API_KEY 环境变量）")
        sys.exit(1)

    print(f"解析 {ORS_HOST} …")
    ors_ip = resolve_via_doh(ORS_HOST)
    print(f"ORS 目标 IP: {ors_ip}\n")

    all_results = {"_ors_ip": ors_ip}
    for town, bbox in CANDIDATES.items():
        print(f"\n=== {town} ===")
        print("  拉取道路节点…")
        pts = fetch_road_nodes(bbox)
        pairs = pick_pairs(pts)
        if not pairs:
            print("  ❌ 道路点不足，无法构造起终点对（路网极稀疏）")
            all_results[town] = [{"error": "路网极稀疏，无法构造试跑点对"}]
            continue
        town_result = []
        for name, start, end in pairs:
            entry = {"pair": name, "start": start, "end": end}
            for profile in PROFILES:
                r = try_route(api_key, ors_ip, profile, start, end)
                entry[profile] = r
                status = (
                    f"✅ {r['distance_m']}m / {r['duration_min']}min"
                    if r["ok"] else f"❌ {r['error']}"
                )
                print(f"  [{profile:12s}] {name}: {status}")
                time.sleep(1.5)  # 免费档 40 次/分钟限速
            town_result.append(entry)
        all_results[town] = town_result

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "town_ors_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {out_path}")


if __name__ == "__main__":
    main()
