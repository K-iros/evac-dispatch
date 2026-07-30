"""API 路由 —— 前端 src/api/client.ts 对应的接口。"""

from fastapi import APIRouter, HTTPException, Query

from app.core.flood import DEFAULT_SCENARIO, SCENARIOS, compute_flood_frames
from app.models.schemas import (
    AccessScanResponse,
    BriefingsResponse,
    FloodFrame,
    RoadbookResponse,
    ScheduleState,
)
from app.services.briefing import build_briefings
from app.services.cv_access import build_access_scan
from app.services.mock_data import build_mock_schedule
from app.services.roadbook import build_roadbook

router = APIRouter(prefix="/api")

#: scenario query 参数的公共声明（功能 C 情景预设）
_SCENARIO_Q = Query(default=DEFAULT_SCENARIO, description="情景键，见 /api/scenarios")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/scenarios")
def get_scenarios() -> list[dict]:
    """情景预设清单（功能 C）：键 + 中文名，默认 s2024。"""
    return [
        {"key": key, "name": name, "isDefault": key == DEFAULT_SCENARIO}
        for key, name in SCENARIOS.items()
    ]


@router.get("/schedule", response_model=ScheduleState, response_model_by_alias=True)
def get_schedule(scenario: str = _SCENARIO_Q) -> ScheduleState:
    """整体调度态势：名单 + 帮扶者 + 避难所 + 匹配结果。

    latestDeparture / arriveBy 由该情景的水深场沿路径反推
    （departure.latest_departure_minutes），与时间轴同一模拟时钟。
    """
    return build_mock_schedule(scenario)


@router.get("/flood/frames", response_model=list[FloodFrame], response_model_by_alias=True)
def get_flood_frames(scenario: str = _SCENARIO_Q) -> list[FloodFrame]:
    """该情景的时变淹没图层序列（landlab OverlandFlow 离线推演帧）。"""
    return compute_flood_frames(scenario)


@router.get("/briefings", response_model=BriefingsResponse, response_model_by_alias=True)
def get_briefings(scenario: str = _SCENARIO_Q) -> BriefingsResponse:
    """AI 派单简报：每位帮扶者一句话任务卡。

    DeepSeek 一次调用生成全部（DEEPSEEK_API_KEY 环境变量），
    无 Key/失败时规则模板兜底，source 字段标注来源。
    """
    return build_briefings(scenario, build_mock_schedule(scenario))


@router.get("/access-scan", response_model=AccessScanResponse,
            response_model_by_alias=True)
def get_access_scan(scenario: str = _SCENARIO_Q) -> AccessScanResponse:
    """CV 补标签半真闭环（第十五节）：预选街景图 → 多模态
    判定轮椅通行障碍（Qwen-VL / 模板兜底），障碍点坐标人工
    预绑定于 accessCases，路径绕行端已由对比开关实现。"""
    return build_access_scan(build_mock_schedule(scenario))


@router.get("/roadbook", response_model=RoadbookResponse, response_model_by_alias=True)
def get_roadbook(evacuee_id: str = Query(alias="evacueeId"),
                 scenario: str = _SCENARIO_Q) -> RoadbookResponse:
    """LLM 语音路书（第十二节 P1）：主路线护送段 → 转向步骤 +
    水情提醒 → 自然语言路书（DeepSeek 润色 / 模板兜底），
    前端 speechSynthesis 播报。"""
    result = build_roadbook(scenario, build_mock_schedule(scenario), evacuee_id)
    if result is None:
        raise HTTPException(status_code=404, detail="该户无主路线，无法生成路书")
    return result
