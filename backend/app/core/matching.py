"""帮扶者-残障者匹配（创新③，第十二节 P1「真实匹配算法」）。

带时间窗的任务分配 + 接送路径问题（VRPTW 变体）：
  志愿者位置 → 残障者家 → 避难所；
  推轮椅段必须走无障碍路径，且必须在该路段失效前通过。

实现口径（贪心 + 时间窗校验 + 串行链）：
1. 每户时间窗 deadline = 住址达画像危险阈值时刻 − 撤离缓冲
   （由调用方用水深场算好传入，本模块不碰淹没帧）；
2. 按 deadline 紧迫度升序逐户指派：候选帮扶者按「接人耗时」
   升序试探，须同时满足
   - 到场校验：接人耗时 ≤ deadline（T0 出发也来不及则不可行）；
   - 串行链校验（最坏情况）：帮扶者已有前一单时，假设前一户拖到
     最迟时刻才离家，前单 deadline + 护送耗时 + 避难所→本户转移
     耗时仍须 ≤ 本户 deadline —— 保证"前单最迟执行也赶得上本单"；
3. 避难所：容量上限 + 轮椅户仅去无障碍避难所，取护送耗时最近者；
4. 冗余匹配：指定户再配 1 名备份帮扶者（不占串行链，纯待命）；
5. 叙事/人工锁单：locked 指定 (helper, shelter) 的户跳过自由选择、
   仅做校验（现实调度同样支持人工锁单），如无障碍绕行案例户；
6. 无可行帮扶者的户输出到 unmatched（→ P0 无路可走清单）。

耗时矩阵由调用方注入（scripts/gen_match_dataset.py 用 Valhalla
sources_to_targets 画像化实算），本模块只做求解。
"""

from dataclasses import dataclass, field

INF = float("inf")


@dataclass
class MatchPlan:
    """单户匹配结果：主帮扶 + 串行次序 + 备份 + 目标避难所。"""

    evacuee_id: str
    helper_id: str
    shelter_id: str
    #: 该帮扶者串行链中的次序（1 起；≥2 即"一人串行接多户"）
    sequence: int
    backup_ids: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    plans: list[MatchPlan]
    #: 无可行帮扶者的户 id → 原因（进 P0 清单）
    unmatched: dict[str, str]
    #: 锁单时间窗告警等非阻断提示
    warnings: list[str] = field(default_factory=list)


@dataclass
class _HelperState:
    """贪心过程中帮扶者的串行链状态。"""

    chain: list[str] = field(default_factory=list)  # 已接户（链序）
    #: 链上最后一单的（户 deadline, 户→避难所耗时, 避难所 id）
    last_deadline: float = 0.0
    last_escort: float = 0.0
    last_shelter: str | None = None


def match_helpers(
    evacuee_ids: list[str],
    helper_ids: list[str],
    shelter_ids: list[str],
    *,
    profile: dict[str, str],
    deadline_min: dict[str, float],
    pickup_min: dict[str, dict[str, float | None]],
    escort_min: dict[str, dict[str, float | None]],
    transfer_min: dict[str, dict[str, float | None]],
    shelter_capacity: dict[str, int],
    shelter_accessible: dict[str, bool],
    locked: dict[str, tuple[str, str]] | None = None,
    with_backup: set[str] | None = None,
    max_chain: int = 3,
) -> MatchResult:
    """求解帮扶者-残障者匹配（贪心 + 时间窗校验 + 串行链）。

    Args:
        evacuee_ids: 待匹配户（未在列的视为无需匹配）
        profile: 户 id → 画像（轮椅户仅可去无障碍避难所）
        deadline_min: 户 id → 最迟离家时刻（模拟分钟，时间窗）
        pickup_min: 帮扶者 id → 户 id → 接人耗时（分钟，None=不可达）
        escort_min: 户 id → 避难所 id → 护送耗时（分钟，按画像步速）
        transfer_min: 避难所 id → 户 id → 转移耗时（串行链下一单）
        locked: 户 id → (帮扶者 id, 避难所 id) 人工锁单（仍做校验）
        with_backup: 需配备份帮扶者的户
        max_chain: 单帮扶者串行上限

    Returns:
        MatchResult：主派计划（含串行次序）+ 未匹配原因。
    """
    locked = locked or {}
    with_backup = with_backup or set()
    states = {h: _HelperState() for h in helper_ids}
    shelter_load = {s: 0 for s in shelter_ids}
    plans: list[MatchPlan] = []
    unmatched: dict[str, str] = {}
    warnings: list[str] = []

    def chain_ok(st: _HelperState, ev: str, helper: str) -> bool:
        """到场 + 串行链最坏情况校验。"""
        ddl = deadline_min[ev]
        if not st.chain:
            first = pickup_min[helper].get(ev)
            return first is not None and first <= ddl
        if len(st.chain) >= max_chain or st.last_shelter is None:
            return False
        hop = transfer_min[st.last_shelter].get(ev)
        if hop is None:
            return False
        return st.last_deadline + st.last_escort + hop <= ddl

    def pick_shelter(ev: str) -> str | None:
        """容量内、画像兼容、护送耗时最近的避难所。"""
        options = [
            s for s in shelter_ids
            if shelter_load[s] < shelter_capacity[s]
            and (profile[ev] != "wheelchair" or shelter_accessible[s])
            and escort_min[ev].get(s) is not None
        ]
        if not options:
            return None
        return min(options, key=lambda s: escort_min[ev][s])  # type: ignore[arg-type]

    def commit(ev: str, helper: str, shelter: str) -> MatchPlan:
        st = states[helper]
        st.chain.append(ev)
        st.last_deadline = deadline_min[ev]
        st.last_escort = escort_min[ev][shelter] or 0.0
        st.last_shelter = shelter
        shelter_load[shelter] += 1
        return MatchPlan(
            evacuee_id=ev, helper_id=helper,
            shelter_id=shelter, sequence=len(st.chain),
        )

    # 紧迫度升序：时间窗最紧的户先挑人（贪心主序）
    for ev in sorted(evacuee_ids, key=lambda e: deadline_min[e]):
        if ev in locked:
            helper, shelter = locked[ev]
            if not chain_ok(states[helper], ev, helper):
                # 锁单不改派（叙事/人工确认优先），仅记录告警
                warnings.append(f"{ev} 锁单（{helper}→{shelter}）时间窗紧张")
            plans.append(commit(ev, helper, shelter))
            continue

        candidates = sorted(
            (h for h in helper_ids if pickup_min[h].get(ev) is not None),
            key=lambda h: pickup_min[h][ev],  # type: ignore[index,return-value]
        )
        assigned = False
        for helper in candidates:
            if not chain_ok(states[helper], ev, helper):
                continue
            shelter = pick_shelter(ev)
            if shelter is None:
                break  # 容量/兼容性耗尽，换人也无济于事
            plans.append(commit(ev, helper, shelter))
            assigned = True
            break
        if not assigned:
            unmatched[ev] = (
                "无避难所容量或不兼容"
                if pick_shelter(ev) is None
                else "所有帮扶者串行链均无法在时间窗内到场"
            )

    # 备份帮扶者：与主帮扶不同、能到场即可（冗余待命，不占链）
    plan_by_ev = {p.evacuee_id: p for p in plans}
    for ev in with_backup:
        plan = plan_by_ev.get(ev)
        if plan is None:
            continue
        ddl = deadline_min[ev]
        for helper in sorted(
            (h for h in helper_ids
             if h != plan.helper_id and pickup_min[h].get(ev) is not None),
            key=lambda h: pickup_min[h][ev],  # type: ignore[index,return-value]
        ):
            if pickup_min[helper][ev] <= ddl:  # type: ignore[operator]
                plan.backup_ids.append(helper)
                break

    return MatchResult(plans=plans, unmatched=unmatched, warnings=warnings)
