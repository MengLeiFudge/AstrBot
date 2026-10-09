from __future__ import annotations

from dataclasses import dataclass
import json
import random
import re
import time


ACTIVATION_WINDOW_SECONDS = 180.0
CANDIDATE_MAX_WAIT_SECONDS = 30.0
SKIP_REPLY_MARKER = "[[QQBOT_SKIP_REPLY]]"
DEACTIVATE_MARKER = "[[QQBOT_DEACTIVATE]]"
POKE_BURST_WINDOW_SECONDS = 60.0
POKE_BURST_MAX_TIMESTAMPS = 16
POKE_MUTE_MIN_POKES = 9
POKE_MUTE_STATE_SECONDS = 30.0
POKE_MUTE_DURATION_MIN_SECONDS = 30
POKE_MUTE_DURATION_MAX_SECONDS = 90
POKE_MUTE_COOLDOWN_SECONDS = 90.0
POKE_MUTE_TOOL_VALID_SECONDS = 120.0
POKE_AI_LEASE_SECONDS = 120.0
POKE_AI_COOLDOWN_SECONDS = 3.0
POKE_BACK_TOOL_NAME = "qqbot_poke_back"
POKE_MUTE_TOOL_NAME = "qqbot_enable_poke_mute"
POKE_STATE_CALM = "CALM"
POKE_STATE_ANNOYED = "ANNOYED"
POKE_STATE_ARMED = "ARMED"
POKE_STATE_MUTE = "MUTE"
EXPLICIT_VISIBLE_RETRY_INSTRUCTION = (
    "上一轮没有产生可发送的可见文本。当前消息是用户对你的显式呼叫，"
    "现在必须重新输出至少一句符合你当前人格的简短可见回复，不能只输出任何内部控制标记。"
    f"如果原消息明确要求你闭嘴、安静或停止说话，先输出一句可见收尾，再在末尾附加 {DEACTIVATE_MARKER}；"
    "其他情况正常回答，不要附加反激活标记。只输出修正后的最终回复。"
)
DUAL_PLATFORM_DUPLICATE_WINDOW_SECONDS = 3.0
FIXED_COMMAND_PREFIX_RE = re.compile(
    r"^(?:文生图|图生图|头像生图)|^(?:棉花糖|棉花)\s*生图|^生成|^(?:查|查询|查看|看)(?:一下)?(?:我(?:的)?|当前)?(?:生图)?积分"
    r"|^积分\s*排行(?:榜)?$"
    r"|^(?:切换\s*)?生图\s*模型(?:\s*\S+)?$"
    r"|^(?:(?:棉花糖|棉花)\s*)?(?:生图|画图)\s*(?:模型(?:说明)?|价格)$"
    r"|^(?:draw\s*models|draw\s*help|balance|points?)$"
    r"|^用量$"
    r"|^(?:菜单|帮助|指令)(?:\s*\S+)?$|^(?:通知)?(?:大家|全员|群友)?(?:清理|整理)(?:群)?文件$|^(?:群)?文件(?:清理|整理)(?:通知)?$"
    r"|^[开关](?:群色图|图片显示)$|^(?:来点)?(?:[美色涩蛇]图|混合).*$"
    r"|^arctj\s*[0-9]+(?:\.[0-9]+)?$|^arc(?:hd|tz)$|^(?:xz|arcxz)$|^(?:arczm|zm)(?:\s*[1-9][0-9]*)?$"
    r"|^jm\s*[0-9]+$"
    r"|^(?:arcqh|qh)(?:\s*(?:[1-9][0-9]*|max))?$|^arcqh\s*(?:bt|补图)$|^(?:arcjx|jx)$"
    r"|^(?:i|view|chart|chart1|chart2|path|path1|path2|p|puzzle|puzzle1|puzzle2) .*$"
    r"|^(?:养鲲|摸鲲|抓鲲|捕鲲|属性|道具|背包|商城|签到|boss|Boss|查看boss|查看Boss|挑战|落樱之都|更新日志|玩法|个人信息|恢复|回复).*$",
    re.IGNORECASE,
)
BOT_NAME_MARKERS = ("棉花糖", "云栖", "萌萌棉花糖", "qqbot")
CALL_ACTION_MARKERS = (
    "帮",
    "帮我",
    "给我",
    "替我",
    "查",
    "查一下",
    "查询",
    "看",
    "看一下",
    "看看",
    "解释",
    "说明",
    "回答",
    "说",
    "说说",
    "评价",
    "点评",
    "分析",
    "生成",
    "画",
    "生图",
    "识别",
    "认",
    "找",
    "推荐",
    "总结",
    "翻译",
    "改写",
    "在吗",
    "在嘛",
    "在不在",
    "出来",
    "说句话",
    "救",
    "救救",
)
STRONG_NON_CALL_MARKERS = (
    "很好吃",
    "好吃",
    "真好吃",
    "挺好吃",
    "不好吃",
    "甜",
    "太甜",
    "糖果",
    "软糖",
    "甜点",
    "零食",
    "棉花糖味",
    "草莓棉花糖",
    "巧克力棉花糖",
    "烤棉花糖",
    "棉花糖机器",
    "棉花糖机",
    "棉花糖工厂",
    "棉花糖皮肤",
    "棉花糖成熟",
    "买棉花糖",
    "卖棉花糖",
)


@dataclass(frozen=True, slots=True)
class CallIntentDecision:
    should_reply: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class GroupActivationState:
    expires_at: float
    ordinary_reply_renewals: int = 0
    generation: int = 0


@dataclass(frozen=True, slots=True)
class ReplyControlDecision:
    cleaned_text: str
    skip_reply: bool = False
    deactivate: bool = False


@dataclass(frozen=True, slots=True)
class PokeBurstObservation:
    """Internal group-level poke pressure; never expose numeric fields to the model."""
    group_id: str
    self_id: str
    sender_id: str
    count: int
    observed_at: float
    state: str
    mute_until: float = 0.0


_GROUP_ACTIVATIONS: dict[tuple[str, str], GroupActivationState] = {}
_GROUP_ACTIVATION_GENERATIONS: dict[tuple[str, str], int] = {}
_POKE_BURST_TIMESTAMPS: dict[tuple[str, str], list[float]] = {}
_POKE_MUTE_UNTIL: dict[tuple[str, str], float] = {}
_POKE_GENERATIONS: dict[tuple[str, str], int] = {}
_POKE_AI_LEASES: dict[tuple[str, str], float] = {}
_POKE_AI_COOLDOWNS: dict[tuple[str, str], float] = {}
_POKE_MUTE_CLAIMS: set[tuple[str, str, str]] = set()
_POKE_MUTE_COOLDOWNS: dict[tuple[str, str, str], float] = {}


def contains_cotton_candy_marker(text: str) -> bool:
    return "棉花糖" in str(text or "") or "qqbot" in str(text or "").lower()


def classify_cotton_candy_call(text: str) -> str:
    """Return call, non_call, or ambiguous for plain text that mentions 棉花糖."""
    raw = str(text or "").strip()
    if not raw:
        return "non_call"
    if looks_like_qqbot_fixed_command(raw):
        return "non_call"
    compact = _compact_call_text(raw)
    if not compact:
        return "non_call"
    normalized_markers = tuple(_compact_call_text(marker) for marker in BOT_NAME_MARKERS)
    if compact in normalized_markers:
        return "call"
    for marker in normalized_markers:
        if compact in {
            f"呼叫{marker}",
            f"叫一下{marker}",
            f"喊一下{marker}",
            f"{marker}在吗",
            f"{marker}在嘛",
            f"{marker}在不在",
            f"{marker}出来",
            f"{marker}说句话",
            f"{marker}回答一下",
            f"{marker}看一下",
        }:
            return "call"
    if _looks_like_strong_non_call(compact):
        return "non_call"
    if _starts_with_bot_name_and_action(compact, normalized_markers):
        return "call"
    if _prefix_calls_bot(compact, normalized_markers):
        return "call"
    if not contains_cotton_candy_marker(raw):
        return "non_call"
    return "ambiguous"


def looks_like_direct_bot_call(text: str) -> bool:
    return classify_cotton_candy_call(text) == "call"


def build_call_intent_prompt(text: str, *, history_lines: list[str] | None = None) -> str:
    lines = [
        "你是 QQ 群机器人“棉花糖”的呼叫判定器，只判断用户这条消息是不是在叫机器人处理当前请求。",
        "必须只返回 JSON，不要解释，不要输出 Markdown。",
        "输出字段：should_reply(boolean), reason(string)。",
        "should_reply=true 只表示应该让其中一只棉花糖进入普通 LLM 回复链路；不要执行固定命令、扣积分、写文件、上传、下载或群管动作。",
        "如果用户只是把“棉花糖”当食物、物件、外号、梗、商品、机器、皮肤或普通名词，should_reply=false。",
        "如果用户在叫棉花糖帮忙、回答、解释、生成、识图、评价、在吗、出来、说句话，should_reply=true。",
        "如果上下文不够，但这句话明显是在喊机器人接话，should_reply=true；如果只是能聊但没有呼叫意图，should_reply=false。",
        "正例：棉花糖，帮我生成一张图片 => true",
        "正例：棉花糖这个图片是哪个角色 => true",
        "反例：棉花糖很好吃 => false",
        "反例：草莓棉花糖在哪买 => false",
    ]
    if history_lines:
        lines.append("最近上下文节选，仅辅助判断是否在叫机器人：")
        lines.extend(line for line in history_lines if line)
    lines.append("用户消息：")
    lines.append(str(text or "").strip())
    return "\n".join(lines)


def parse_call_intent_response(text: str) -> CallIntentDecision | None:
    try:
        payload = _extract_json_object(text)
    except Exception:
        return None
    return CallIntentDecision(
        should_reply=bool(payload.get("should_reply")),
        reason=str(payload.get("reason") or "").strip()[:160],
    )


def activate_group_chat(
    group_id: object,
    worker_id: object,
    *,
    now: float | None = None,
) -> GroupActivationState | None:
    key = _activation_key(group_id, worker_id)
    if key is None:
        return None
    current = time.monotonic() if now is None else now
    generation = _GROUP_ACTIVATION_GENERATIONS.get(key, 0) + 1
    _GROUP_ACTIVATION_GENERATIONS[key] = generation
    state = GroupActivationState(
        expires_at=current + ACTIVATION_WINDOW_SECONDS,
        ordinary_reply_renewals=0,
        generation=generation,
    )
    _GROUP_ACTIVATIONS[key] = state
    return state


def read_group_activation(
    group_id: object,
    worker_id: object,
    *,
    now: float | None = None,
) -> GroupActivationState | None:
    key = _activation_key(group_id, worker_id)
    if key is None:
        return None
    state = _GROUP_ACTIVATIONS.get(key)
    if state is None:
        return None
    current = time.monotonic() if now is None else now
    if state.expires_at <= current:
        _GROUP_ACTIVATIONS.pop(key, None)
        return None
    return state


def is_candidate_request_current(
    group_id: object,
    worker_id: object,
    *,
    expected_generation: int,
    queued_at: float,
    now: float | None = None,
    max_wait_seconds: float = CANDIDATE_MAX_WAIT_SECONDS,
) -> bool:
    current = time.monotonic() if now is None else now
    if expected_generation <= 0 or queued_at <= 0:
        return False
    if current - queued_at > max(0.0, max_wait_seconds):
        return False
    state = read_group_activation(group_id, worker_id, now=current)
    return state is not None and state.generation == expected_generation


def renew_group_chat_after_reply(
    group_id: object,
    worker_id: object,
    *,
    explicit: bool,
    expected_generation: int | None = None,
    now: float | None = None,
) -> GroupActivationState | None:
    key = _activation_key(group_id, worker_id)
    if key is None:
        return None
    current = time.monotonic() if now is None else now
    previous = _GROUP_ACTIVATIONS.get(key)
    latest_generation = _GROUP_ACTIVATION_GENERATIONS.get(key, 0)
    if expected_generation is None:
        if previous is None:
            return None
        expected_generation = previous.generation
    if expected_generation <= 0:
        return None
    if latest_generation != expected_generation:
        return None
    if previous is not None and previous.generation != expected_generation:
        return None
    renewals = 0 if explicit else (previous.ordinary_reply_renewals + 1 if previous else 1)
    state = GroupActivationState(
        expires_at=current + ACTIVATION_WINDOW_SECONDS,
        ordinary_reply_renewals=renewals,
        generation=expected_generation,
    )
    _GROUP_ACTIVATIONS[key] = state
    return state


def deactivate_group_chat(
    group_id: object,
    worker_id: object,
    *,
    expected_generation: int | None = None,
) -> bool:
    key = _activation_key(group_id, worker_id)
    if key is None:
        return False
    previous = _GROUP_ACTIVATIONS.get(key)
    latest_generation = _GROUP_ACTIVATION_GENERATIONS.get(key, 0)
    if expected_generation is None:
        if previous is None:
            return False
        expected_generation = previous.generation
    if expected_generation <= 0:
        return False
    if latest_generation != expected_generation:
        return False
    if previous is not None and previous.generation != expected_generation:
        return False
    _GROUP_ACTIVATIONS.pop(key, None)
    _GROUP_ACTIVATION_GENERATIONS[key] = expected_generation + 1
    return True


def clear_group_activations() -> None:
    _GROUP_ACTIVATIONS.clear()
    _GROUP_ACTIVATION_GENERATIONS.clear()


def clear_poke_interaction_state() -> None:
    """Clear all reload-scoped poke interaction state."""
    _POKE_BURST_TIMESTAMPS.clear()
    _POKE_MUTE_UNTIL.clear()
    _POKE_GENERATIONS.clear()
    _POKE_AI_LEASES.clear()
    _POKE_AI_COOLDOWNS.clear()
    _POKE_MUTE_CLAIMS.clear()
    _POKE_MUTE_COOLDOWNS.clear()


def record_poke_burst(
    group_id: object,
    self_id: object,
    sender_id: object,
    *,
    now: float | None = None,
    window_seconds: float = POKE_BURST_WINDOW_SECONDS,
) -> PokeBurstObservation | None:
    """Record a poke into group+self pressure, aggregating all human senders."""
    group_key = _poke_group_key(group_id, self_id)
    sender_key = str(sender_id or "").strip()
    if group_key is None or not sender_key:
        return None
    current = time.monotonic() if now is None else float(now)
    _prune_poke_global_state(now=current, window_seconds=window_seconds)
    mute_until = _POKE_MUTE_UNTIL.get(group_key, 0.0)
    if mute_until > current:
        return PokeBurstObservation(
            group_id=group_key[0], self_id=group_key[1], sender_id=sender_key,
            count=POKE_MUTE_MIN_POKES, observed_at=current,
            state=POKE_STATE_MUTE, mute_until=mute_until,
        )

    stamps = _active_poke_stamps(group_key, now=current, window_seconds=window_seconds)
    stamps.append(current)
    stamps = stamps[-POKE_BURST_MAX_TIMESTAMPS:]
    _POKE_BURST_TIMESTAMPS[group_key] = stamps
    state = _poke_pressure_state(len(stamps))
    if state == POKE_STATE_MUTE:
        mute_until = enter_poke_mute(group_key[0], group_key[1], now=current)
    return PokeBurstObservation(
        group_id=group_key[0], self_id=group_key[1], sender_id=sender_key,
        count=len(stamps), observed_at=current, state=state, mute_until=mute_until,
    )


def read_poke_burst(
    group_id: object,
    self_id: object,
    sender_id: object = "",
    *,
    now: float | None = None,
    window_seconds: float = POKE_BURST_WINDOW_SECONDS,
) -> PokeBurstObservation | None:
    group_key = _poke_group_key(group_id, self_id)
    if group_key is None:
        return None
    current = time.monotonic() if now is None else float(now)
    _prune_poke_global_state(now=current, window_seconds=window_seconds)
    mute_until = _POKE_MUTE_UNTIL.get(group_key, 0.0)
    if mute_until > current:
        return PokeBurstObservation(
            group_id=group_key[0], self_id=group_key[1], sender_id=str(sender_id or ""),
            count=POKE_MUTE_MIN_POKES, observed_at=current,
            state=POKE_STATE_MUTE, mute_until=mute_until,
        )
    stamps = _active_poke_stamps(group_key, now=current, window_seconds=window_seconds)
    if not stamps:
        return None
    return PokeBurstObservation(
        group_id=group_key[0], self_id=group_key[1], sender_id=str(sender_id or ""),
        count=len(stamps), observed_at=stamps[-1], state=_poke_pressure_state(len(stamps)),
    )


def enter_poke_mute(
    group_id: object,
    self_id: object,
    *,
    now: float | None = None,
    duration_seconds: float = POKE_MUTE_STATE_SECONDS,
) -> float:
    """Enter MUTE and discard old pressure so expiry starts from a clean baseline."""
    key = _poke_group_key(group_id, self_id)
    if key is None:
        return 0.0
    current = time.monotonic() if now is None else float(now)
    until = current + max(0.0, float(duration_seconds))
    _POKE_MUTE_UNTIL[key] = until
    _POKE_GENERATIONS[key] = _POKE_GENERATIONS.get(key, 0) + 1
    _POKE_BURST_TIMESTAMPS.pop(key, None)
    _POKE_AI_LEASES.pop(key, None)
    _POKE_AI_COOLDOWNS.pop(key, None)
    return until


def read_poke_generation(group_id: object, self_id: object) -> int:
    key = _poke_group_key(group_id, self_id)
    if key is None:
        return -1
    return _POKE_GENERATIONS.get(key, 0)


def is_poke_request_current(
    group_id: object,
    self_id: object,
    *,
    expected_generation: int,
) -> bool:
    key = _poke_group_key(group_id, self_id)
    return key is not None and expected_generation >= 0 and (
        _POKE_GENERATIONS.get(key, 0) == expected_generation
    )


def try_acquire_poke_ai(
    group_id: object,
    self_id: object,
    *,
    now: float | None = None,
    lease_seconds: float = POKE_AI_LEASE_SECONDS,
) -> bool:
    key = _poke_group_key(group_id, self_id)
    if key is None:
        return False
    current = time.monotonic() if now is None else float(now)
    _prune_poke_global_state(now=current)
    if _POKE_MUTE_UNTIL.get(key, 0.0) > current:
        return False
    if _POKE_AI_LEASES.get(key, 0.0) > current:
        return False
    if _POKE_AI_COOLDOWNS.get(key, 0.0) > current:
        return False
    _POKE_AI_LEASES[key] = current + max(0.0, float(lease_seconds))
    return True


def release_poke_ai(
    group_id: object,
    self_id: object,
    *,
    now: float | None = None,
    cooldown_seconds: float = POKE_AI_COOLDOWN_SECONDS,
) -> None:
    key = _poke_group_key(group_id, self_id)
    if key is None:
        return
    current = time.monotonic() if now is None else float(now)
    _POKE_AI_LEASES.pop(key, None)
    _POKE_AI_COOLDOWNS[key] = current + max(0.0, float(cooldown_seconds))


def is_poke_mute_tool_eligible(
    *,
    poke_count: int,
    observed_at: float,
    group_id: object,
    self_id: object,
    sender_id: object,
    now: float | None = None,
    min_pokes: int = 6,
    tool_valid_seconds: float = POKE_MUTE_TOOL_VALID_SECONDS,
) -> bool:
    """ARMED requests alone may expose the state transition tool."""
    key = _poke_key(group_id, self_id, sender_id)
    if key is None or int(poke_count) < max(1, int(min_pokes)) or int(poke_count) >= POKE_MUTE_MIN_POKES:
        return False
    current = time.monotonic() if now is None else float(now)
    observed = float(observed_at)
    return 0.0 < observed <= current and current - observed <= max(0.0, float(tool_valid_seconds))


def try_claim_poke_mute(group_id: object, self_id: object, sender_id: object) -> bool:
    key = _poke_key(group_id, self_id, sender_id)
    if key is None or key in _POKE_MUTE_CLAIMS:
        return False
    _POKE_MUTE_CLAIMS.add(key)
    return True


def release_poke_mute_claim(group_id: object, self_id: object, sender_id: object) -> None:
    key = _poke_key(group_id, self_id, sender_id)
    if key is not None:
        _POKE_MUTE_CLAIMS.discard(key)


def mark_poke_mute_success(
    group_id: object,
    self_id: object,
    sender_id: object,
    *,
    now: float | None = None,
    cooldown_seconds: float = POKE_MUTE_COOLDOWN_SECONDS,
) -> None:
    key = _poke_key(group_id, self_id, sender_id)
    if key is None:
        return
    current = time.monotonic() if now is None else float(now)
    _POKE_MUTE_CLAIMS.discard(key)
    _POKE_MUTE_COOLDOWNS[key] = current + max(0.0, float(cooldown_seconds))


def can_mute_poker(
    group_id: object,
    self_id: object,
    sender_id: object,
    *,
    now: float | None = None,
) -> bool:
    key = _poke_key(group_id, self_id, sender_id)
    if key is None:
        return False
    current = time.monotonic() if now is None else float(now)
    _prune_poke_global_state(now=current)
    return key not in _POKE_MUTE_CLAIMS and _POKE_MUTE_COOLDOWNS.get(key, 0.0) <= current


def pick_poke_mute_duration(
    *,
    rng: random.Random | None = None,
    min_seconds: int = POKE_MUTE_DURATION_MIN_SECONDS,
    max_seconds: int = POKE_MUTE_DURATION_MAX_SECONDS,
) -> int:
    low = max(1, int(min_seconds))
    high = max(low, int(max_seconds))
    chooser = rng if rng is not None else random
    return int(chooser.randint(low, high))


def validate_poke_mute_execution(
    *,
    event_group_id: object,
    event_self_id: object,
    event_sender_id: object,
    captured_sender_id: object,
    captured_count: int,
    observed_at: float,
    now: float | None = None,
    min_pokes: int = 6,
    tool_valid_seconds: float = POKE_MUTE_TOOL_VALID_SECONDS,
) -> str:
    group_key = str(event_group_id or "").strip()
    self_key = str(event_self_id or "").strip()
    sender_key = str(event_sender_id or "").strip()
    captured_sender = str(captured_sender_id or "").strip()
    if not group_key or not self_key or not sender_key:
        return "invalid_event"
    if captured_sender != sender_key:
        return "sender_mismatch"
    current = time.monotonic() if now is None else float(now)
    observed = float(observed_at)
    if observed <= 0 or current - observed > max(0.0, float(tool_valid_seconds)):
        return "observation_expired"
    if observed > current:
        return "observation_in_future"
    if not (max(1, int(min_pokes)) <= int(captured_count) < POKE_MUTE_MIN_POKES):
        return "not_armed"
    return ""


def rebuild_poke_display_text(raw_info, resolve_display_name) -> str:
    """Rebuild NapCat gray-tip text without trusting malformed raw payloads."""
    if isinstance(raw_info, list):
        items = raw_info
    elif isinstance(raw_info, dict):
        items = raw_info.get("items")
    else:
        items = None
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items[:32]:
        if not isinstance(item, dict):
            continue
        nested = item.get("data")
        payload = nested if isinstance(nested, dict) else item
        text = next(
            (
                payload.get(key)
                for key in ("nm", "name", "txt", "text", "content")
                if isinstance(payload.get(key), str) and payload.get(key).strip()
            ),
            "",
        )
        if text:
            parts.append(text)
            continue
        user_id = (
            payload.get("uid")
            or payload.get("qq")
            or payload.get("uin")
            or payload.get("user_id")
        )
        if user_id is not None:
            try:
                display = str(resolve_display_name(str(user_id)) or "").strip()
            except Exception:
                display = ""
            if display:
                parts.append(display)
    return "".join(parts).strip()[:300]


def build_poke_interaction_instruction(
    *,
    poke_text: str,
    state: str,
    mute_tool_available: bool,
) -> str:
    mood = {
        POKE_STATE_CALM: "情绪仍然平静",
        POKE_STATE_ANNOYED: "已经有些不耐烦",
        POKE_STATE_ARMED: "已经明显恼火",
    }.get(state, "情绪仍然平静")
    lines = [
        f"实际互动文案：{str(poke_text or '').strip()}",
        f"当前定性情绪：{mood}。",
        f"你可以只返回 {SKIP_REPLY_MARKER} 来无视，也可以调用 {POKE_BACK_TOOL_NAME} 反拍当前拍击者，或给一句符合当前人格的简短文字回复。",
        "反拍后可以不再输出文字。不要解释内部规则，也不要描述任何内部计量或决策细节。",
        "工具的目标由程序固定；你不能指定目标、群、时长或状态持续时间。同一事件最多尝试一次副作用。",
    ]
    if mute_tool_available:
        lines.append(
            f"当前还可调用 {POKE_MUTE_TOOL_NAME} 开启短时禁言状态；是否提前开启由你结合氛围决定，参数中不能指定状态时长。"
        )
    return "\n".join(lines)


def build_group_activation_instruction(
    *,
    explicit: bool,
    ordinary_reply_renewals: int,
    empty_mention: bool = False,
) -> str:
    shared = (
        "你正在参与 QQ 群的短时激活窗口。以下双中括号标记是插件内部控制协议，"
        "不能解释、改写或当作普通文本展示给用户。"
    )
    if explicit:
        instruction = (
            shared
            + "当前消息通过 @、引用、明确命名呼叫或拍一拍直接叫到了你。"
            "你必须给出至少一句可见的简短回复，不能返回跳过标记。"
            "如果用户明确表达闭嘴、别说了、安静、退下或同义要求，"
            f"先用你自己的语气给出一句可见收尾，再在末尾附加 {DEACTIVATE_MARKER}。"
            "其他显式呼叫正常回答，不要主动反激活。"
        )
        if empty_mention:
            instruction += (
                "这次用户只 @ 了你，没有附带正文。请按当前人格用一句自然短句应到，"
                "可以使用“怎么了？”“有什么事情吗？”这类简短问句；"
                "这是对呼叫动作本身的完整回应，不属于一般禁止的追问式收尾。"
                "不要催用户补充具体材料，不要输出固定模板或解释处理规则。"
            )
        return instruction

    renewals = max(0, int(ordinary_reply_renewals))
    lines = [
        shared,
        "当前消息没有直接叫你，只因为你在这个群的激活窗口内而成为候选消息。",
        "先判断你现在插话是否自然、有新增价值、没有抢别人话和重复群友已经说清的内容。",
        f"不值得回复时必须只返回 {SKIP_REPLY_MARKER}，不要附带解释、表情或其他文字。",
        "如果决定可见回复，回复会把激活窗口重新续到 3 分钟。",
        f"当前已经因普通候选回复连续续期 {renewals} 次。",
        f"话题已经自然收尾、继续说只会刷屏或你已经参与够多时，可以只返回 {DEACTIVATE_MARKER}，"
        f"也可以先给一句必要的简短收尾，再在末尾附加 {DEACTIVATE_MARKER}。",
    ]
    if renewals >= 4:
        lines.append(
            "连续续期已经很多。当前消息如果明确表示问题解决、谢谢收尾、大家继续聊、不再需要你或话题结束，"
            f"必须返回 {DEACTIVATE_MARKER}，不能只返回跳过标记；可以在标记前保留一句确有必要的简短收尾。"
            "其他消息除非确实缺少你的关键回答，否则优先跳过；继续可见回复时也要优先寻找本轮反激活时机。"
        )
    elif renewals >= 2:
        lines.append(
            "你已经连续续期多次。提高沉默倾向，只在明显有价值时继续回复，并主动寻找自然反激活时机。"
        )
    else:
        lines.append("默认保持克制：能不插话就跳过，有明确价值才回复。")
    lines.append(f"不能同时输出 {SKIP_REPLY_MARKER} 和 {DEACTIVATE_MARKER}。")
    return "\n".join(lines)


def parse_reply_control(text: str) -> ReplyControlDecision:
    raw = str(text or "")
    skip_reply = SKIP_REPLY_MARKER in raw
    deactivate = DEACTIVATE_MARKER in raw
    cleaned = raw.replace(SKIP_REPLY_MARKER, "").replace(DEACTIVATE_MARKER, "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).strip()
    return ReplyControlDecision(
        cleaned_text=cleaned,
        skip_reply=skip_reply,
        deactivate=deactivate,
    )


def rewrite_last_assistant_history(messages, *, replacement_text: str = "") -> None:
    if not isinstance(messages, list):
        return
    replacement = str(replacement_text or "").strip()
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if str(getattr(message, "role", "") or "") != "assistant":
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            message.content = replacement or parse_reply_control(content).cleaned_text
        elif isinstance(content, list):
            cleaned_parts = []
            replacement_applied = False
            for part in content:
                part_text = _history_text_part_value(part)
                if part_text is None:
                    cleaned_parts.append(part)
                    continue
                cleaned = replacement if replacement and not replacement_applied else parse_reply_control(part_text).cleaned_text
                if not cleaned:
                    continue
                _set_history_text_part_value(part, cleaned)
                cleaned_parts.append(part)
                replacement_applied = replacement_applied or bool(replacement)
            if replacement and not replacement_applied:
                message.content = replacement
            else:
                message.content = cleaned_parts
        elif replacement:
            message.content = replacement
        if not message.content and not getattr(message, "tool_calls", None):
            messages.pop(index)
        return


def should_activate_from_poke(
    *,
    self_id: object,
    user_id: object,
    target_id: object,
    bot_ids: tuple[str, ...] | frozenset[str],
) -> bool:
    self_key = str(self_id or "").strip()
    user_key = str(user_id or "").strip()
    target_key = str(target_id or "").strip()
    if not self_key or not user_key or not target_key:
        return False
    if target_key != self_key or user_key == self_key:
        return False
    return user_key not in set(bot_ids)


def should_normalize_empty_mention(
    *,
    self_id: object,
    at_target_ids: tuple[str, ...],
    has_other_content: bool,
) -> bool:
    self_key = str(self_id or "").strip()
    targets = tuple(str(target or "").strip() for target in at_target_ids)
    return bool(self_key) and targets == (self_key,) and not has_other_content


async def chat_with_current_provider(
    *,
    context,
    event,
    prompt: str,
    session_id: str | None = None,
    logger,
):
    provider = read_current_provider(context, event, logger)
    provider_id = read_provider_id(provider)
    if provider is None:
        logger.info("[TopicConcentration] no provider for call intent decision")
        return None

    try:
        response = await provider.text_chat(
            prompt=prompt,
            session_id=session_id or f"topic_concentration:{event.unified_msg_origin}",
            persist=False,
        )
    except Exception as exc:
        logger.warning(
            "[TopicConcentration] call intent provider failed: provider=%s error=%s",
            provider_id,
            exc,
        )
        return None
    logger.debug("[TopicConcentration] call intent provider succeeded: provider=%s", provider_id)
    return response


async def retry_explicit_visible_reply(
    *,
    context,
    event,
    request,
    logger,
):
    provider = read_current_provider(context, event, logger)
    provider_id = read_provider_id(provider)
    if provider is None or request is None:
        logger.warning(
            "[TopicConcentration] cannot retry explicit visible reply: provider=%s request=%s",
            provider_id,
            bool(request),
        )
        return None

    try:
        current_message = await request.assemble_context()
        contexts = list(getattr(request, "contexts", None) or [])
        contexts.append(current_message)
        response = await provider.text_chat(
            prompt=EXPLICIT_VISIBLE_RETRY_INSTRUCTION,
            contexts=contexts,
            system_prompt=str(getattr(request, "system_prompt", "") or ""),
            model=getattr(request, "model", None),
            func_tool=None,
            request_max_retries=1,
        )
    except Exception as exc:
        logger.warning(
            "[TopicConcentration] explicit visible reply retry failed: provider=%s error=%s",
            provider_id,
            exc,
        )
        return None
    logger.info(
        "[TopicConcentration] explicit visible reply retry completed: provider=%s has_text=%s",
        provider_id,
        bool(str(getattr(response, "completion_text", "") or "").strip()),
    )
    return response


def read_current_provider(context, event, logger):
    try:
        return context.get_using_provider(event.unified_msg_origin)
    except Exception as exc:
        logger.warning("[TopicConcentration] failed to read current provider: %s", exc)
        return None


def read_provider_id(provider) -> str:
    if provider is None:
        return ""
    provider_config = getattr(provider, "provider_config", None)
    if not isinstance(provider_config, dict):
        return ""
    return str(provider_config.get("id") or "").strip()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def normalize_observed_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def has_strong_topic_signal(text: str) -> bool:
    compact = compact_text(text).lower()
    if not compact or looks_like_low_information(text):
        return False
    strong_markers = (
        "?",
        "？",
        "请问",
        "求助",
        "有人知道",
        "谁知道",
        "怎么",
        "咋",
        "为啥",
        "为什么",
        "报错",
        "错误",
        "异常",
        "配置",
        "代码",
        "接口",
        "日志",
        "打不开",
        "不生效",
        "mod",
        "模组",
        "星环",
        "factorio",
        "shapez",
        "astrbot",
        "nonebot",
        "napcat",
    )
    return any(marker in compact for marker in strong_markers)


def looks_like_low_information(text: str) -> bool:
    compact = compact_text(text).lower()
    if not compact:
        return True
    core = re.sub(r"[?!？！，,。.~～…、]+", "", compact)
    if not core:
        return True
    low_interjections = {
        "咪",
        "咪咪",
        "喵",
        "喵喵",
        "啊",
        "啊啊",
        "嗯",
        "嗯嗯",
        "哦",
        "噢",
        "额",
        "呃",
        "诶",
        "欸",
        "哈",
        "哈哈",
    }
    if len(core) <= 4 and core in low_interjections:
        return True
    low_markers = ("哈哈", "草", "笑死", "乐", "确实", "对啊", "是吧", "好耶", "离谱")
    return len(compact) <= 12 and any(marker in compact for marker in low_markers)


def looks_like_short_presence_probe(text: str) -> bool:
    core = _compact_call_text(text)
    return core in {"在吗", "在嘛", "在不在", "还在吗", "人呢"}


def looks_like_qqbot_fixed_command(text: str) -> bool:
    return FIXED_COMMAND_PREFIX_RE.search(str(text or "").strip()) is not None


def is_recent_duplicate_observation(
    window,
    *,
    text: str,
    user_id: str,
    now: float,
    duplicate_window_seconds: float = DUAL_PLATFORM_DUPLICATE_WINDOW_SECONDS,
) -> bool:
    normalized = normalize_observed_text(text)
    if not normalized or not user_id:
        return False
    for message in reversed(window):
        created_at = float(getattr(message, "created_at", 0.0) or 0.0)
        if now - created_at > duplicate_window_seconds:
            return False
        if str(getattr(message, "user_id", "") or "") == user_id and normalize_observed_text(
            getattr(message, "text", "")
        ) == normalized:
            return True
    return False


def read_config_value(config, key: str, default):
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    try:
        return config[key]
    except Exception:
        return default


def _activation_key(group_id: object, worker_id: object) -> tuple[str, str] | None:
    group_key = str(group_id or "").strip()
    worker_key = str(worker_id or "").strip()
    if not group_key or not worker_key:
        return None
    return group_key, worker_key


def _poke_group_key(group_id: object, self_id: object) -> tuple[str, str] | None:
    group_key = str(group_id or "").strip()
    self_key = str(self_id or "").strip()
    if not group_key or not self_key:
        return None
    return group_key, self_key


def _poke_key(
    group_id: object,
    self_id: object,
    sender_id: object,
) -> tuple[str, str, str] | None:
    group_key = str(group_id or "").strip()
    self_key = str(self_id or "").strip()
    sender_key = str(sender_id or "").strip()
    if not group_key or not self_key or not sender_key:
        return None
    return group_key, self_key, sender_key


def _active_poke_stamps(
    key: tuple[str, str],
    *,
    now: float,
    window_seconds: float = POKE_BURST_WINDOW_SECONDS,
) -> list[float]:
    window = max(0.0, float(window_seconds))
    stamps = [stamp for stamp in _POKE_BURST_TIMESTAMPS.get(key, []) if now - stamp <= window and stamp <= now]
    if len(stamps) > POKE_BURST_MAX_TIMESTAMPS:
        stamps = stamps[-POKE_BURST_MAX_TIMESTAMPS:]
    if stamps:
        _POKE_BURST_TIMESTAMPS[key] = stamps
    else:
        _POKE_BURST_TIMESTAMPS.pop(key, None)
    return stamps


def _prune_poke_global_state(
    *,
    now: float,
    window_seconds: float = POKE_BURST_WINDOW_SECONDS,
) -> None:
    window = max(0.0, float(window_seconds))
    expired_burst_keys = [
        key
        for key, stamps in list(_POKE_BURST_TIMESTAMPS.items())
        if not any(now - stamp <= window and stamp <= now for stamp in stamps)
    ]
    for key in expired_burst_keys:
        _POKE_BURST_TIMESTAMPS.pop(key, None)
    for state in (_POKE_MUTE_UNTIL, _POKE_AI_LEASES, _POKE_AI_COOLDOWNS):
        for key, until in list(state.items()):
            if until <= now:
                state.pop(key, None)
    expired_cooldown_keys = [
        key for key, until in list(_POKE_MUTE_COOLDOWNS.items()) if until <= now
    ]
    for key in expired_cooldown_keys:
        _POKE_MUTE_COOLDOWNS.pop(key, None)


def _poke_pressure_state(count: int) -> str:
    if count >= POKE_MUTE_MIN_POKES:
        return POKE_STATE_MUTE
    if count >= 6:
        return POKE_STATE_ARMED
    if count >= 3:
        return POKE_STATE_ANNOYED
    return POKE_STATE_CALM


def _history_text_part_value(part) -> str | None:
    if isinstance(part, dict):
        if str(part.get("type") or "") != "text":
            return None
        return str(part.get("text") or "")
    if not hasattr(part, "text"):
        return None
    return str(getattr(part, "text", "") or "")


def _set_history_text_part_value(part, text: str) -> None:
    if isinstance(part, dict):
        part["text"] = text
    else:
        part.text = text


def _starts_with_bot_name_and_action(compact: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if not compact.startswith(marker):
            continue
        rest = compact[len(marker) :]
        if not rest:
            return True
        if rest.startswith(("，", ",", "。", ".", "：", ":", "？", "?")):
            return True
        if rest.endswith(("吗", "嘛", "？", "?")) and len(rest) <= 12:
            return True
        compact_actions = tuple(_compact_call_text(action) for action in CALL_ACTION_MARKERS)
        if any(rest.startswith(action) for action in compact_actions):
            return True
        if any(len(action) >= 2 and action in rest[:12] for action in compact_actions):
            return True
    return False


def _prefix_calls_bot(compact: str, markers: tuple[str, ...]) -> bool:
    prefixes = ("呼叫", "叫一下", "喊一下", "召唤")
    return any(compact.startswith(f"{prefix}{marker}") for prefix in prefixes for marker in markers)


def _looks_like_strong_non_call(compact: str) -> bool:
    if any(_compact_call_text(marker) in compact for marker in STRONG_NON_CALL_MARKERS):
        return True
    if "棉花糖" not in compact:
        return False
    if re.search(r"(?:吃|买|卖|烤|做|制作|生产|机器|皮肤|工厂|味|口味)", compact):
        return not any(_compact_call_text(action) in compact for action in CALL_ACTION_MARKERS)
    return False


def _compact_call_text(text: str) -> str:
    compact = compact_text(text).lower()
    return re.sub(r"[?!？！，,。.~～…、:：；;\s]+", "", compact)


def _extract_json_object(text: str) -> dict[str, object]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match is None:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("call intent decision is not a JSON object")
    return data
