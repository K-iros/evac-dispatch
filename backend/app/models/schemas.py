"""Pydantic 数据模型 —— 字段与前端 src/types.ts 对齐（输出 camelCase）。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

Profile = Literal["wheelchair", "blind", "elderly"]
# escorting：时间驱动状态机的"护送中"（第十三节第 4 项，前端派生态，
# 后端不主动输出，保留枚举与前端 types.ts 对齐）
MatchStatus = Literal[
    "unmatched", "matched", "en_route", "escorting", "arrived", "evacuated"
]
AlertLevel = Literal["standby", "ready", "dispatch"]


class CamelModel(BaseModel):
    """序列化为 camelCase，与前端字段命名一致。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LngLat(CamelModel):
    lng: float
    lat: float


class Evacuee(CamelModel):
    id: str
    name: str
    profile: Profile
    address: str
    location: LngLat
    latest_departure: str  # ISO 8601，核心计算产物
    match_status: MatchStatus
    helper_ids: list[str]  # 冗余匹配：首选 + 备份
    shelter_id: str | None


class Helper(CamelModel):
    id: str
    name: str
    location: LngLat
    assigned_evacuee_ids: list[str]
    available: bool


class Shelter(CamelModel):
    id: str
    name: str
    location: LngLat
    wheelchair_accessible: bool
    #: 容量/预派人数（第十三节第 5 项：满员信息透出，弹窗「容量 2/2 已满」）
    capacity: int | None = None
    occupancy: int | None = None
    #: 校舍类多层建筑（第十三节第 7 项）：场地进水时可垂直避险，
    #: 前端降级为黄色「仅垂直避险」而非红叉失效
    vertical_refuge: bool = False


class DeriveStep(CamelModel):
    """最迟出发时间倒推链的单步中间量（第十五节：可解释性透出）。

    倒推序（首元素为路径末段）：每步先被该段失效时刻收紧
    latest = min(latest, fail_minute)，再扣减该段通行耗时，
    latest_after 为扣减后的值（模拟分钟）。
    """

    seg_index: int  # 路径小段序号（顶点 i → i+1）
    phase: Literal["pickup", "escort"]  # 接人段 / 护送段
    fail_minute: float | None  # 该段失效时刻；None = 全程可通行
    duration_min: float  # 该段通行耗时（分钟）
    latest_after: float  # 递推后 latest（可为负，负值即无可行时间窗）
    clamped: bool  # 该段失效时刻是否实际收紧了 latest


class Assignment(CamelModel):
    """一条调度任务：帮扶者 → 残障者家 → 避难所。"""

    helper_id: str
    evacuee_id: str
    shelter_id: str
    arrive_by: str
    is_backup: bool
    #: 串行链次序（第十二节 P1 真实匹配算法）：同一帮扶者按此
    #: 顺序依次执行主派任务，≥2 即"一人串行接多户"（前一单送达
    #: 避难所后再出发接下一户，路线起点为前一单的避难所）
    sequence: int = 1
    #: 避难所失效时的改派候选路线（功能 D）：默认不渲染，
    #: 目标避难所被淹/急流超限时由前端自动升级为主路线
    is_fallback: bool = False
    route: list[tuple[float, float]]  # GeoJSON LineString coordinates
    #: 普通步行对照路线（无障碍对比开关，仅对比案例户有值）：
    #: 与 route（轮椅无障碍绕行）同航点的 Valhalla type=foot 实算结果
    foot_route: list[tuple[float, float]] | None = None
    #: 时间口径一致性（第十三节第 6 项 (a)）：本单按当前路线反推的
    #: 帮扶者最迟出发时刻；串行链下的最早可行开始时刻（前序任务从
    #: T0 即刻执行的最早完成时刻）；depart_by < earliest_start 即
    #: conflict —— 系统识别出的不可行排班（红色冲突告警）
    depart_by: str | None = None
    earliest_start: str | None = None
    conflict: bool = False
    #: 最迟出发时间倒推链（第十五节）：把 latest_departure_minutes
    #: 已算出的逐段中间量透出，前端点击最迟出发时间展开白箱推导
    derive_steps: list[DeriveStep] = []


class ShelterTransfer(CamelModel):
    """避难所间转移路线（第十三节第 8-2 项：已入住人员二次转移）。

    离线预生成「失效时刻更早的所 → 更晚/全程安全的所」定向路线，
    按两所直线距离升序排列；避难所失效时前端取首个目标可用且
    路线按所内最弱画像阈值仍可通行的条目批量转移。
    """

    from_shelter_id: str
    to_shelter_id: str
    route: list[tuple[float, float]]


class AccessBarrier(CamelModel):
    """无障碍障碍点（OSM 真实台阶/窄巷）：对比开关的 ⚠️ 标注。"""

    location: LngLat
    label: str  # 如「台阶，轮椅不可通行」


class AccessCase(CamelModel):
    """无障碍对比案例（第十二节 P0）：轮椅绕行 vs 普通步行同屏双线。"""

    evacuee_id: str
    barrier: AccessBarrier
    wheelchair_km: float
    foot_km: float
    detour_ratio: float  # 绕行倍率 = wheelchair_km / foot_km


class FloodFrame(CamelModel):
    """某一时刻的淹没图层（landlab 推演帧）。

    geojson feature 属性：minDepth（水深分档下限 m）或
    minVd（v·d 失稳分档下限 m²/s，功能 B 危险度判据）。
    """

    minute: int
    water_level: float  # 相对常水位涨幅（m，向后兼容）
    stage_m: float | None = None  # 阳朔站绝对水位（m）
    warn_m: float | None = None  # 超警戒水位幅度（m，负值=低于警戒）
    clock: str | None = None  # 模拟时钟 ISO 时刻（与最迟出发时间同坐标系）
    geojson: dict  # GeoJSON FeatureCollection


class ScheduleState(CamelModel):
    alert_level: AlertLevel
    evacuees: list[Evacuee]
    helpers: list[Helper]
    shelters: list[Shelter]
    assignments: list[Assignment]
    #: 无障碍对比案例（对比开关数据源，无案例时为空）
    access_cases: list[AccessCase] = []
    #: 避难所间转移路线（二次转移预案，第十三节第 8-2 项）
    shelter_transfers: list[ShelterTransfer] = []


class Briefing(CamelModel):
    """单个帮扶者的派单简报（一句话任务卡）。"""

    helper_id: str
    helper_name: str
    text: str


class BriefingsResponse(CamelModel):
    """AI 派单简报（第十二节 P0）：DeepSeek 生成，失败时模板兜底。"""

    source: Literal["llm", "template"]
    items: list[Briefing]


class RoadbookResponse(CamelModel):
    """LLM 语音路书（第十二节 P1）：盲人画像路径 → 自然语言路书 → TTS。

    text 为可直接朗读的整段路书；steps 为几何转向步骤清单
    （从主路线护送段折线提取，叠加水深场失效时刻提示）。
    """

    evacuee_id: str
    evacuee_name: str
    helper_name: str | None
    shelter_name: str | None
    source: Literal["llm", "template"]
    text: str
    steps: list[str]
    distance_km: float
    duration_min: int


class AccessScanItem(CamelModel):
    """单张街景的 CV 障碍识别结果（第十五节：CV 补标签半真闭环）。

    预选街景图 + 多模态大模型判定，障碍点坐标人工预绑定
    （accessCases.barrier）；演示链路：照片 → AI 判定有台阶 →
    地图亮 ⚠️ → 轮椅路线绕行（后两段已由对比开关实现）。
    """

    evacuee_id: str
    image: str  # 前端可访问的街景图 URL（/streetview/{id}.png）
    verdict: str  # AI 判定文本（存在台阶/陡坎，轮椅不可通行…）
    barrier_detected: bool = True


class AccessScanResponse(CamelModel):
    """/api/access-scan 响应：多模态识别，失败时模板兜底。"""

    source: Literal["llm", "template"]
    items: list[AccessScanItem]
