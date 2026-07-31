# -*- coding: utf-8 -*-
"""调度结果落盘缓存预计算（第二期决策 1，模式照抄 run_flood_sim.py）。

对三情景强制实时计算 build_mock_schedule 的完整结果（最迟出发时间
反推链纯 CPU 密集，约 9 分钟/情景），连同输入文件 SHA256 指纹导出
backend/data/schedule_{scenario}.json，**提交进仓库**随镜像分发——
后端重启时 mock_data 指纹匹配即毫秒级加载，冷启动 9 分钟归零。

用法（本地跑一次约 27 分钟，一劳永逸）：
    python scripts/gen_schedule_cache.py            # 全部三情景
    python scripts/gen_schedule_cache.py s2024      # 指定情景

改了 yangshuo_schedule.json 或重跑了洪水模拟后必须重跑本脚本，
并把更新后的 schedule_*.json 与代码同一提交推送（V2 发布纪律）。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.core.flood import SCENARIOS  # noqa: E402
from app.services.mock_data import (  # noqa: E402
    _cache_path,
    _compute_schedule,
    _input_fingerprint,
    _write_schedule_cache,
)


def gen_scenario(key):
    """强制实时计算一个情景并写落盘缓存（不走已有缓存）。"""
    fingerprint = _input_fingerprint(key)
    if fingerprint is None:
        print("[%s] 输入文件缺失（洪水帧未预计算？），跳过" % key)
        return
    t0 = time.time()
    state = _compute_schedule(key)
    elapsed = time.time() - t0
    _write_schedule_cache(key, fingerprint, state)
    path = _cache_path(key)
    no_window = sum(1 for a in state.assignments if a.depart_by is None)
    print("[%s] 已写入 %s（%d 户 / %d 派单，其中无可行时间窗 %d 条，"
          "%.1f MB，计算耗时 %.0fs）" % (
              key, path, len(state.evacuees), len(state.assignments),
              no_window, os.path.getsize(path) / 1e6, elapsed))


def main():
    keys = sys.argv[1:] or list(SCENARIOS)
    for key in keys:
        if key not in SCENARIOS:
            print("未知情景键: %s（可选 %s）" % (key, "/".join(SCENARIOS)))
            continue
        gen_scenario(key)


if __name__ == "__main__":
    main()
