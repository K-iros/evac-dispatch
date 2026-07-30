"""离线预计算数据与在线接口逐字段一致性验证。

验证三件事（三情景 s30/s2024/extreme 全覆盖）：
1. flood_frames_{key}.json 原始字段经 FloodFrame 模型规范化后与
   GET /api/flood/frames 响应深度一致，且原始文件无被模型丢弃的多余键
   （文件 snake_case → 接口 camelCase 由 populate_by_name 别名映射）；
2. build_mock_schedule(key) 离线序列化（model_dump by_alias）与
   GET /api/schedule 响应深度一致 —— 两个独立进程各自计算得到相同
   结果，同时证明可离线固化与算法确定性；
3. 前端回退 frontend/src/mock/scheduleDataset.json 与在线 s2024 一致。

用法：先启动后端（uvicorn :8000），再
  backend/.venv/Scripts/python.exe scripts/verify_offline_parity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.flood import compute_flood_frames  # noqa: E402
from app.models.schemas import FloodFrame  # noqa: E402
from app.services.mock_data import build_mock_schedule  # noqa: E402

BASE = "http://127.0.0.1:8000"
SCENARIOS = ["s30", "s2024", "extreme"]
MAX_REPORT = 8  # 每项比对最多列出的差异条数


def deep_diff(a, b, path: str = "$", out: list[str] | None = None) -> list[str]:
    """递归比对：键集合 / 列表长度 / 标量值，返回差异路径清单。"""
    if out is None:
        out = []
    if len(out) > 200:  # 防爆
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() - b.keys():
            out.append(f"{path}.{k} 仅离线侧存在")
        for k in b.keys() - a.keys():
            out.append(f"{path}.{k} 仅在线侧存在")
        for k in a.keys() & b.keys():
            deep_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path} 长度不一致：离线 {len(a)} vs 在线 {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path} 值不一致：离线 {a!r} vs 在线 {b!r}")
    return out


def report(label: str, diffs: list[str]) -> bool:
    if not diffs:
        print(f"  ✓ {label}：逐字段一致")
        return True
    print(f"  ✗ {label}：{len(diffs)} 处差异")
    for d in diffs[:MAX_REPORT]:
        print(f"      {d}")
    if len(diffs) > MAX_REPORT:
        print(f"      …（其余 {len(diffs) - MAX_REPORT} 处省略）")
    return False


def main() -> None:
    ok = True
    client = httpx.Client(base_url=BASE, timeout=900.0)

    for sc in SCENARIOS:
        print(f"\n===== 情景 {sc} =====")

        # --- 1. 淹没帧：原始文件 → 模型规范化 vs 在线接口 ---
        raw_path = ROOT / "backend" / "data" / f"flood_frames_{sc}.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        model_fields = set(FloodFrame.model_fields)
        extra = {k for f in raw for k in f} - model_fields
        if extra:
            ok = report(f"flood_frames_{sc}.json 键覆盖", [f"$ 存在被模型丢弃的键 {sorted(extra)}"]) and ok
        else:
            print(f"  ✓ flood_frames_{sc}.json 键覆盖：{len(raw)} 帧，无被丢弃键")

        offline_frames = [
            f.model_dump(mode="json", by_alias=True) for f in compute_flood_frames(sc)
        ]
        online_frames = client.get("/api/flood/frames", params={"scenario": sc}).json()
        ok = report("淹没帧 离线序列化 vs /api/flood/frames", deep_diff(offline_frames, online_frames)) and ok

        # 原始文件（别名归一后）与在线响应的等值性：证明接口未改写数值
        normalized_raw = [
            FloodFrame(**f).model_dump(mode="json", by_alias=True) for f in raw
        ]
        ok = report("原始文件规范化 vs /api/flood/frames", deep_diff(normalized_raw, online_frames)) and ok

        # --- 2. 调度态势：离线 build vs 在线接口（独立进程各算一遍） ---
        offline_state = build_mock_schedule(sc).model_dump(mode="json", by_alias=True)
        online_state = client.get("/api/schedule", params={"scenario": sc}).json()
        ok = report("build_mock_schedule 离线序列化 vs /api/schedule", deep_diff(offline_state, online_state)) and ok
        n_steps = sum(len(a.get("deriveSteps", [])) for a in offline_state["assignments"])
        print(
            f"    （{len(offline_state['evacuees'])} 户 / "
            f"{len(offline_state['assignments'])} 任务 / deriveSteps {n_steps} 步，可离线固化）"
        )

    # --- 3. 前端回退 JSON（s2024 固化产物）vs 在线 ---
    print("\n===== 前端回退固化产物 =====")
    frontend = json.loads(
        (ROOT / "frontend" / "src" / "mock" / "scheduleDataset.json").read_text(encoding="utf-8")
    )
    online_s2024 = client.get("/api/schedule", params={"scenario": "s2024"}).json()
    ok = report("scheduleDataset.json vs /api/schedule?scenario=s2024", deep_diff(frontend, online_s2024)) and ok

    print("\n" + ("全部通过 ✅" if ok else "存在差异 ❌"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
