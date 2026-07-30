# -*- coding: utf-8 -*-
"""CV 补标签半真闭环（第十五节）：街景图 → 多模态判定无障碍障碍。

闭环定位：注入端（障碍点坐标 + Valhalla 绕行实算）与路径改变端
已由 scripts/gen_access_compare.py 100% 完成，本服务补上最前面的
"从街景图识别台阶"一环——预选 3 张阳朔风格街景图（对应 3 个对比
案例户），障碍点坐标人工预绑定，回避相机位姿估计深坑。

生成策略（与 briefing/roadbook 同一模式）：
1. 有 DASHSCOPE_API_KEY 时调用 Qwen-VL（qwen-vl-plus，OpenAI 兼容
   接口，图片 base64 内联），逐图判定是否存在轮椅通行障碍；
2. 无 Key / 调用失败 / 图片缺失时，用预置模板判定兜底
   （source 字段标注来源，演示不会空白）。
"""

import base64
import logging
import os
from pathlib import Path

import httpx

from app.models.schemas import AccessScanItem, AccessScanResponse, ScheduleState

logger = logging.getLogger(__name__)

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DASHSCOPE_MODEL = "qwen-vl-plus"
DASHSCOPE_TIMEOUT = 60.0

#: 街景图目录：与前端 public/streetview 同一份文件（Vite 静态服务），
#: 后端仅在多模态调用时读取原图做 base64 内联
STREETVIEW_DIR = (
    Path(__file__).resolve().parents[3] / "frontend" / "public" / "streetview"
)

#: 模板兜底判定（与预选街景图内容一致的口径；LLM 可用时被实时判定覆盖）
TEMPLATE_VERDICTS: dict[str, str] = {
    "e-8": "存在障碍：巷口连续石阶约 5 级，无坡道，轮椅不可通行",
    "e-14": "存在障碍：路缘陡坎高约 20cm 且路面破损，轮椅不可通行",
    "e-19": "存在障碍：临街台阶带残缺护栏，无缘石坡道，轮椅不可通行",
}
FALLBACK_VERDICT = "存在障碍：识别到台阶/陡坎，轮椅不可通行"

_PROMPT = (
    "你是社区无障碍设施审查员。判断这张街景照片中的通行路段是否存在"
    "轮椅通行障碍（台阶、陡坎、无坡道等）。只输出一句话结论（35字内），"
    "以「存在障碍：」或「无障碍可通行：」开头，说明看到的具体障碍物。"
)

#: LLM 结果缓存（案例集不随情景变化，整份响应缓存一次即可；
#: 模板兜底不缓存，便于配 Key 后重试）
_llm_cache: AccessScanResponse | None = None


def _image_url(evacuee_id: str) -> str:
    return f"/streetview/{evacuee_id}.png"


def _call_qwen_vl(api_key: str, image_path: Path) -> str:
    """单图判定：Qwen-VL OpenAI 兼容接口，base64 内联。"""
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    resp = httpx.post(
        DASHSCOPE_URL,
        timeout=DASHSCOPE_TIMEOUT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": DASHSCOPE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
            "temperature": 0.2,
        },
    )
    resp.raise_for_status()
    return str(resp.json()["choices"][0]["message"]["content"]).strip()


def _template_items(case_ids: list[str]) -> list[AccessScanItem]:
    return [
        AccessScanItem(
            evacuee_id=ev_id,
            image=_image_url(ev_id),
            verdict=TEMPLATE_VERDICTS.get(ev_id, FALLBACK_VERDICT),
            barrier_detected=True,
        )
        for ev_id in case_ids
    ]


def build_access_scan(state: ScheduleState) -> AccessScanResponse:
    """街景识别入口：Qwen-VL 优先，任何失败走模板兜底。"""
    global _llm_cache
    if _llm_cache is not None:
        return _llm_cache

    case_ids = [c.evacuee_id for c in state.access_cases]
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return AccessScanResponse(source="template", items=_template_items(case_ids))

    items: list[AccessScanItem] = []
    any_llm = False
    for ev_id in case_ids:
        image_path = STREETVIEW_DIR / f"{ev_id}.png"
        verdict = TEMPLATE_VERDICTS.get(ev_id, FALLBACK_VERDICT)
        if image_path.is_file():
            try:
                verdict = _call_qwen_vl(api_key, image_path)
                any_llm = True
            except Exception as exc:  # noqa: BLE001 —— 网络/配额失败均兜底
                logger.warning("Qwen-VL 街景识别失败（%s），走模板兜底: %s", ev_id, exc)
        items.append(
            AccessScanItem(
                evacuee_id=ev_id,
                image=_image_url(ev_id),
                verdict=verdict,
                barrier_detected="无障碍可通行" not in verdict,
            )
        )
    result = AccessScanResponse(source="llm" if any_llm else "template", items=items)
    if any_llm:
        _llm_cache = result
    return result
