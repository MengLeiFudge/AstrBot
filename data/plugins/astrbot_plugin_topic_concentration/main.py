from __future__ import annotations

import time
from asyncio import CancelledError

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.message_components import At, Plain, Poke, Reply
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.star.filter.event_message_type import EventMessageType

from .logic import ACTIVATION_WINDOW_SECONDS
from .logic import CANDIDATE_MAX_WAIT_SECONDS
from .logic import DEACTIVATE_MARKER
from .logic import POKE_BACK_TOOL_NAME
from .logic import POKE_MUTE_TOOL_NAME
from .logic import POKE_STATE_ARMED
from .logic import POKE_STATE_MUTE
from .logic import SKIP_REPLY_MARKER
from .logic import activate_group_chat
from .logic import build_call_intent_prompt
from .logic import build_group_activation_instruction
from .logic import build_poke_interaction_instruction
from .logic import can_mute_poker
from .logic import chat_with_current_provider as _chat_with_current_decision_provider
from .logic import classify_cotton_candy_call
from .logic import clear_group_activations
from .logic import clear_poke_interaction_state
from .logic import contains_cotton_candy_marker
from .logic import deactivate_group_chat
from .logic import enter_poke_mute
from .logic import is_candidate_request_current
from .logic import is_poke_mute_tool_eligible
from .logic import is_poke_request_current
from .logic import looks_like_qqbot_fixed_command
from .logic import mark_poke_mute_success
from .logic import parse_call_intent_response
from .logic import parse_reply_control
from .logic import pick_poke_mute_duration
from .logic import read_group_activation
from .logic import read_poke_generation
from .logic import rebuild_poke_display_text
from .logic import record_poke_burst
from .logic import release_poke_ai
from .logic import release_poke_mute_claim
from .logic import renew_group_chat_after_reply
from .logic import retry_explicit_visible_reply
from .logic import rewrite_last_assistant_history
from .logic import should_activate_from_poke
from .logic import should_normalize_empty_mention
from .logic import try_acquire_poke_ai
from .logic import try_claim_poke_mute
from .logic import validate_poke_mute_execution
try:
    from astrbot_plugin_qqbot_features.bot_identity import KNOWN_SISTER_BOT_QQ_IDS
except ModuleNotFoundError:  # AstrBot runtime imports plugins as data.plugins.<name>.
    from data.plugins.astrbot_plugin_qqbot_features.bot_identity import KNOWN_SISTER_BOT_QQ_IDS


YUNQI_QQ = "1443944862"
CURRENT_BOT_ID_EXTRA = "_qqbot_group_activation_bot_id"
LLM_ROUTE_EXTRA = "_qqbot_group_activation_route"
ACTIVATION_RENEWALS_EXTRA = "_qqbot_group_activation_renewals"
ACTIVATION_GENERATION_EXTRA = "_qqbot_group_activation_generation"
ACTIVATION_REQUEST_EXTRA = "_qqbot_group_activation_provider_request"
RETRY_VISIBLE_TEXT_EXTRA = "_qqbot_group_activation_retry_visible_text"
PENDING_STATE_ACTION_EXTRA = "_qqbot_group_activation_pending_action"
CANDIDATE_QUEUED_AT_EXTRA = "_qqbot_group_activation_candidate_queued_at"
CANDIDATE_RESERVED_EXTRA = "_qqbot_group_activation_candidate_reserved"
EMPTY_MENTION_CALL_EXTRA = "_qqbot_empty_mention_call"
POKE_INTERACTION_EXTRA = "_qqbot_poke_interaction"
POKE_COUNT_EXTRA = "_qqbot_poke_count"
POKE_SENDER_EXTRA = "_qqbot_poke_sender_id"
POKE_OBSERVED_AT_EXTRA = "_qqbot_poke_observed_at"
POKE_STATE_EXTRA = "_qqbot_poke_state"
POKE_TEXT_EXTRA = "_qqbot_poke_text"
POKE_AI_RESERVED_EXTRA = "_qqbot_poke_ai_reserved"
POKE_GENERATION_EXTRA = "_qqbot_poke_generation"
POKE_SIDE_EFFECT_ATTEMPTED_EXTRA = "_qqbot_poke_side_effect_attempted"
POKE_MUTE_ATTEMPTED_EXTRA = POKE_SIDE_EFFECT_ATTEMPTED_EXTRA
ROUTE_PRIVATE = "private"
ROUTE_EXPLICIT = "explicit"
ROUTE_CANDIDATE = "candidate"
ACTION_RENEW_EXPLICIT = "renew_explicit"
ACTION_RENEW_CANDIDATE = "renew_candidate"
ACTION_DEACTIVATE = "deactivate"
ACTION_ACTIVATE_POKE = "activate_poke"
POKE_CALL_TEXT = "用户拍了拍你"
EMPTY_MENTION_CALL_TEXT = "用户只@了你，没有附带其他内容"


@register(
    "astrbot_plugin_topic_concentration",
    "MengLei",
    "棉花糖群聊激活状态、显式呼叫与单账号普通 LLM 路由。",
    "0.6.0",
)
class TopicConcentrationPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        clear_group_activations()
        clear_poke_interaction_state()
        logger.info(
            "[TopicConcentration] loaded Yunqi group activation gate: activation_seconds=%.0f markers=%s,%s",
            ACTIVATION_WINDOW_SECONDS,
            SKIP_REPLY_MARKER,
            DEACTIVATE_MARKER,
        )

    @filter.event_message_type(EventMessageType.ALL, priority=1000, desc="群聊激活状态与云栖普通 LLM 路由；固定命令不参与。")
    async def route_llm_event(self, event):
        poke_target_id = _current_poke_target_id(event)
        if not _is_candidate_event(event, poke_target_id=poke_target_id):
            return
        at_ids = _at_target_ids(event)
        self_id = str(event.get_self_id() or "").strip()
        empty_mention = not event.is_private_chat() and should_normalize_empty_mention(
            self_id=self_id,
            at_target_ids=at_ids,
            has_other_content=_has_other_message_content(event),
        )
        if poke_target_id:
            poke_text = _current_poke_text(event)
            event.message_str = poke_text
            poke_observation = record_poke_burst(
                event.get_group_id(), self_id, event.get_sender_id()
            )
            if poke_observation is None:
                return
            event.set_extra(POKE_INTERACTION_EXTRA, "1")
            event.set_extra(POKE_COUNT_EXTRA, poke_observation.count)
            event.set_extra(POKE_SENDER_EXTRA, poke_observation.sender_id)
            event.set_extra(POKE_OBSERVED_AT_EXTRA, poke_observation.observed_at)
            event.set_extra(POKE_STATE_EXTRA, poke_observation.state)
            event.set_extra(POKE_TEXT_EXTRA, poke_text)
            logger.info(
                "[TopicConcentration] poke pressure: group=%s self=%s sender=%s state=%s count=%s",
                poke_observation.group_id, poke_observation.self_id,
                poke_observation.sender_id, poke_observation.state, poke_observation.count,
            )
            if poke_observation.state == POKE_STATE_MUTE:
                await _mute_current_poker(event, source="mute_state")
                event.should_call_llm(True)
                event.stop_event()
                return
            if not try_acquire_poke_ai(event.get_group_id(), self_id):
                event.should_call_llm(True)
                event.stop_event()
                logger.info(
                    "[TopicConcentration] throttle poke AI: group=%s self=%s sender=%s",
                    event.get_group_id(), self_id, event.get_sender_id(),
                )
                return
            event.set_extra(POKE_AI_RESERVED_EXTRA, "1")
            event.set_extra(
                POKE_GENERATION_EXTRA,
                read_poke_generation(event.get_group_id(), self_id),
            )
        elif empty_mention:
            event.message_str = EMPTY_MENTION_CALL_TEXT
            event.set_extra(EMPTY_MENTION_CALL_EXTRA, "1")
        text = _plain_text(event) or str(event.get_message_str() or "")
        if looks_like_qqbot_fixed_command(text):
            return

        reply_target_id = _reply_target_id(event)
        route = ""
        reason = ""
        activation_state = None

        if event.is_private_chat():
            route = ROUTE_PRIVATE
            reason = "private"
        elif poke_target_id:
            route = ROUTE_EXPLICIT
            reason = "poke"
        elif empty_mention:
            route = ROUTE_EXPLICIT
            reason = "empty_mention"
        elif self_id in at_ids or reply_target_id == self_id:
            route = ROUTE_EXPLICIT
            reason = "direct"
        elif getattr(event, "is_at_or_wake_command", False):
            route = ROUTE_EXPLICIT
            reason = "direct_wake"
        else:
            activation_state = read_group_activation(event.get_group_id(), self_id)
            if contains_cotton_candy_marker(text):
                call_reason = await _decide_named_call(self.context, event, text)
                if call_reason is not None:
                    route = ROUTE_EXPLICIT
                    reason = call_reason
                elif activation_state is None:
                    event.should_call_llm(True)
                    event.stop_event()
                    return
            if not route and activation_state is not None:
                route = ROUTE_CANDIDATE
                reason = "active_candidate"
            if not route:
                return

        if route == ROUTE_CANDIDATE:
            event.set_extra(CANDIDATE_RESERVED_EXTRA, "1")
            event.set_extra(CANDIDATE_QUEUED_AT_EXTRA, time.monotonic())

        if route == ROUTE_EXPLICIT and not poke_target_id:
            activation_state = activate_group_chat(event.get_group_id(), self_id)

        event.is_wake = True
        event.is_at_or_wake_command = True
        event.set_extra(CURRENT_BOT_ID_EXTRA, self_id)
        event.set_extra(LLM_ROUTE_EXTRA, route)
        event.set_extra(
            ACTIVATION_RENEWALS_EXTRA,
            activation_state.ordinary_reply_renewals if activation_state is not None else 0,
        )
        event.set_extra(
            ACTIVATION_GENERATION_EXTRA,
            activation_state.generation if activation_state is not None else 0,
        )
        logger.info(
            "[TopicConcentration] allow LLM: self=%s route=%s trigger=%s renewals=%s group=%s",
            self_id,
            route,
            reason,
            activation_state.ordinary_reply_renewals if activation_state is not None else 0,
            event.get_group_id(),
        )

    @filter.on_waiting_llm_request(priority=1000, desc="候选进入 AstrBot 会话锁前检查激活代际与排队时效。")
    async def validate_candidate_before_queue(self, event):
        if str(event.get_extra(LLM_ROUTE_EXTRA, "") or "") != ROUTE_CANDIDATE:
            return
        if _candidate_request_is_current(event):
            return
        _stop_stale_candidate(event, stage="waiting")

    @filter.on_llm_request(desc="校验当前云栖请求并注入群聊激活控制协议。")
    async def prepare_llm_route(self, event, req):
        selected = str(event.get_extra(CURRENT_BOT_ID_EXTRA, "") or "")
        if not selected:
            return
        if selected != str(event.get_self_id() or ""):
            event.should_call_llm(True)
            event.stop_event()
            return
        route = str(event.get_extra(LLM_ROUTE_EXTRA, "") or "")
        if route == ROUTE_CANDIDATE and not _candidate_request_is_current(event):
            _stop_stale_candidate(event, stage="provider")
            return
        is_poke = bool(event.get_extra(POKE_INTERACTION_EXTRA, ""))
        if route in {ROUTE_EXPLICIT, ROUTE_CANDIDATE} and not is_poke:
            renewals = int(event.get_extra(ACTIVATION_RENEWALS_EXTRA, 0) or 0)
            req.extra_user_content_parts.append(
                TextPart(
                    text=build_group_activation_instruction(
                        explicit=route == ROUTE_EXPLICIT,
                        ordinary_reply_renewals=renewals,
                        empty_mention=bool(event.get_extra(EMPTY_MENTION_CALL_EXTRA, "")),
                    )
                ).mark_as_temp()
            )
        poke_count = int(event.get_extra(POKE_COUNT_EXTRA, 0) or 0)
        mute_tool_attached = False
        if route == ROUTE_EXPLICIT and is_poke:
            mute_tool_attached = _attach_poke_tools(self, event, req, poke_count=poke_count)
            req.extra_user_content_parts.append(
                TextPart(
                    text=build_poke_interaction_instruction(
                        poke_text=str(event.get_extra(POKE_TEXT_EXTRA, POKE_CALL_TEXT) or POKE_CALL_TEXT),
                        state=str(event.get_extra(POKE_STATE_EXTRA, "") or ""),
                        mute_tool_available=mute_tool_attached,
                    )
                ).mark_as_temp()
            )
        if route == ROUTE_EXPLICIT:
            event.set_extra(ACTIVATION_REQUEST_EXTRA, req)
        logger.info(
            "[TopicConcentration] prepare LLM route: bot=%s session=%s request_session=%s route=%s renewals=%s poke_count=%s mute_tool=%s markers=%s,%s",
            selected,
            getattr(event, "unified_msg_origin", ""),
            getattr(req, "session_id", ""),
            route,
            int(event.get_extra(ACTIVATION_RENEWALS_EXTRA, 0) or 0),
            poke_count,
            mute_tool_attached,
            SKIP_REPLY_MARKER,
            DEACTIVATE_MARKER,
        )

    async def qqbot_poke_back(self, event) -> str:
        """Request-scoped reaction locked to the current poker."""
        failure = _claim_poke_side_effect(event)
        if failure:
            return f"poke_rejected: {failure}"
        try:
            call_action = getattr(getattr(event, "bot", None), "call_action", None)
            if not callable(call_action):
                raise RuntimeError("missing_bot_call_action")
            await call_action(
                "send_poke",
                group_id=str(event.get_group_id() or ""),
                user_id=str(event.get_sender_id() or ""),
            )
            return "poke_success"
        except CancelledError:
            raise
        except Exception as exc:
            logger.warning("[TopicConcentration] poke back failed: error_type=%s", type(exc).__name__)
            return f"poke_failed: {type(exc).__name__}"

    async def qqbot_enable_poke_mute(self, event, reason: str = "") -> str:
        """ARMED-only transition; target, ban duration, and state duration are fixed."""
        del reason
        failure = _claim_poke_side_effect(event)
        if failure:
            return f"mute_rejected: {failure}"
        group_id = event.get_group_id()
        self_id = str(event.get_self_id() or "").strip()
        sender_id = str(event.get_sender_id() or "").strip()
        failure = validate_poke_mute_execution(
            event_group_id=group_id,
            event_self_id=self_id,
            event_sender_id=sender_id,
            captured_sender_id=event.get_extra(POKE_SENDER_EXTRA, ""),
            captured_count=int(event.get_extra(POKE_COUNT_EXTRA, 0) or 0),
            observed_at=float(event.get_extra(POKE_OBSERVED_AT_EXTRA, 0.0) or 0.0),
        )
        if failure:
            return f"mute_rejected: {failure}"
        success, detail = await _mute_current_poker(event, source="armed_tool")
        if not success:
            return detail
        enter_poke_mute(group_id, self_id)
        return detail

    @filter.on_llm_response(
        priority=1000,
        desc="完成当前云栖请求，优先消费候选跳过/反激活标记并登记发送后的状态动作。",
    )
    async def finish_llm_route(self, event, response):
        selected = str(event.get_extra(CURRENT_BOT_ID_EXTRA, "") or "")
        if not selected:
            return
        route = str(event.get_extra(LLM_ROUTE_EXTRA, "") or "")
        is_poke = bool(event.get_extra(POKE_INTERACTION_EXTRA, ""))
        if event.get_extra(POKE_AI_RESERVED_EXTRA, ""):
            release_poke_ai(event.get_group_id(), event.get_self_id())
            event.set_extra(POKE_AI_RESERVED_EXTRA, "")
        candidate_current = route != ROUTE_CANDIDATE or _candidate_request_is_current(event)
        poke_current = not is_poke or _poke_request_is_current(event)
        if route == ROUTE_CANDIDATE:
            event.set_extra(CANDIDATE_RESERVED_EXTRA, "")
        if not poke_current:
            event.set_extra(PENDING_STATE_ACTION_EXTRA, "")
            event.set_extra(RETRY_VISIBLE_TEXT_EXTRA, "")
            _apply_reply_control(response, "", suppress=True)
            logger.info(
                "[TopicConcentration] suppress stale poke response: bot=%s group=%s generation=%s",
                selected,
                event.get_group_id(),
                int(event.get_extra(POKE_GENERATION_EXTRA, -1) or 0),
            )
            return
        if not candidate_current:
            _apply_reply_control(response, "", suppress=True)
            logger.info(
                "[TopicConcentration] suppress stale candidate response: bot=%s group=%s generation=%s",
                selected,
                event.get_group_id(),
                int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0),
            )
            return
        raw_text = _response_text(response)
        control = parse_reply_control(raw_text) if route in {ROUTE_EXPLICIT, ROUTE_CANDIDATE} else None
        if route == ROUTE_EXPLICIT and not is_poke and control is not None and not control.cleaned_text:
            retry_response = await retry_explicit_visible_reply(
                context=self.context,
                event=event,
                request=event.get_extra(ACTIVATION_REQUEST_EXTRA),
                logger=logger,
            )
            retry_text = _response_text(retry_response)
            retry_control = parse_reply_control(retry_text) if retry_text else None
            if retry_control is not None and retry_control.cleaned_text and response is not None:
                response.completion_text = retry_text
                event.set_extra(RETRY_VISIBLE_TEXT_EXTRA, retry_control.cleaned_text)
                raw_text = retry_text
                control = retry_control
            else:
                if response is not None:
                    _apply_reply_control(response, "", suppress=True)
                control = parse_reply_control("")
                logger.error(
                    "[TopicConcentration] explicit visible reply retry still invalid: bot=%s group=%s",
                    selected,
                    event.get_group_id(),
                )
        suppress_reply = bool(
            control and control.skip_reply and (route == ROUTE_CANDIDATE or is_poke)
        )
        if control is not None and (control.skip_reply or control.deactivate):
            _apply_reply_control(response, control.cleaned_text, suppress=suppress_reply or not control.cleaned_text)

        cleaned_text = _response_text(response)
        visible_reply = bool(cleaned_text)

        if suppress_reply:
            if control and control.deactivate:
                deactivate_group_chat(
                    event.get_group_id(),
                    selected,
                    expected_generation=int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0),
                )
            logger.info(
                "[TopicConcentration] model skipped candidate reply: bot=%s group=%s renewals=%s deactivate=%s",
                selected,
                event.get_group_id(),
                int(event.get_extra(ACTIVATION_RENEWALS_EXTRA, 0) or 0),
                bool(control and control.deactivate),
            )
            return

        if control and control.deactivate:
            if visible_reply:
                event.set_extra(PENDING_STATE_ACTION_EXTRA, ACTION_DEACTIVATE)
            else:
                deactivate_group_chat(
                    event.get_group_id(),
                    selected,
                    expected_generation=int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0),
                )
        elif visible_reply and route == ROUTE_EXPLICIT:
            event.set_extra(
                PENDING_STATE_ACTION_EXTRA,
                ACTION_ACTIVATE_POKE if is_poke else ACTION_RENEW_EXPLICIT,
            )
        elif visible_reply and route == ROUTE_CANDIDATE:
            event.set_extra(PENDING_STATE_ACTION_EXTRA, ACTION_RENEW_CANDIDATE)

        if control and control.skip_reply and route == ROUTE_EXPLICIT:
            logger.warning(
                "[TopicConcentration] explicit reply contained forbidden skip marker: bot=%s group=%s has_visible_text=%s",
                selected,
                event.get_group_id(),
                visible_reply,
            )
        logger.info(
            "[TopicConcentration] release LLM route: bot=%s session=%s route=%s visible=%s skip=%s deactivate=%s pending=%s",
            selected,
            getattr(event, "unified_msg_origin", ""),
            route,
            visible_reply,
            bool(control and control.skip_reply),
            bool(control and control.deactivate),
            event.get_extra(PENDING_STATE_ACTION_EXTRA, ""),
        )

    @filter.on_agent_done(desc="从即将持久化的 assistant 历史中移除群聊激活内部控制标记。")
    async def strip_activation_markers_from_history(self, event, run_context, response):
        if str(event.get_extra(LLM_ROUTE_EXTRA, "") or "") not in {ROUTE_EXPLICIT, ROUTE_CANDIDATE}:
            return
        rewrite_last_assistant_history(
            getattr(run_context, "messages", None),
            replacement_text=str(event.get_extra(RETRY_VISIBLE_TEXT_EXTRA, "") or ""),
        )

    @filter.after_message_sent(desc="普通 LLM 消息发送后刷新或关闭当前群当前 bot 的激活状态。")
    async def update_activation_after_message_sent(self, event):
        action = str(event.get_extra(PENDING_STATE_ACTION_EXTRA, "") or "")
        selected = str(event.get_extra(CURRENT_BOT_ID_EXTRA, "") or "")
        if not action or not selected or event.is_private_chat():
            return
        group_id = event.get_group_id()
        generation = int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0)
        if action == ACTION_DEACTIVATE:
            applied = deactivate_group_chat(
                group_id,
                selected,
                expected_generation=generation,
            )
            state = None
        elif action == ACTION_ACTIVATE_POKE:
            state = activate_group_chat(group_id, selected)
            applied = state is not None
        elif action == ACTION_RENEW_EXPLICIT:
            state = renew_group_chat_after_reply(
                group_id,
                selected,
                explicit=True,
                expected_generation=generation,
            )
            applied = state is not None
        elif action == ACTION_RENEW_CANDIDATE:
            state = renew_group_chat_after_reply(
                group_id,
                selected,
                explicit=False,
                expected_generation=generation,
            )
            applied = state is not None
        else:
            return
        event.set_extra(PENDING_STATE_ACTION_EXTRA, "")
        logger.info(
            "[TopicConcentration] applied group activation state: action=%s group=%s bot=%s generation=%s applied=%s renewals=%s",
            action,
            group_id,
            selected,
            generation,
            applied,
            state.ordinary_reply_renewals if state is not None else 0,
        )


def _attach_poke_tools(plugin, event, req, *, poke_count: int) -> bool:
    group_id = event.get_group_id()
    self_id = str(event.get_self_id() or "").strip()
    sender_id = str(event.get_extra(POKE_SENDER_EXTRA, "") or event.get_sender_id() or "").strip()
    observed_at = float(event.get_extra(POKE_OBSERVED_AT_EXTRA, 0.0) or 0.0)
    state = str(event.get_extra(POKE_STATE_EXTRA, "") or "")
    if getattr(req, "func_tool", None) is None:
        req.func_tool = ToolSet()
    mute_tool_attached = False
    if state == POKE_STATE_ARMED and is_poke_mute_tool_eligible(
        poke_count=poke_count, observed_at=observed_at,
        group_id=group_id, self_id=self_id, sender_id=sender_id,
    ):
        req.func_tool.add_tool(FunctionTool(
            name=POKE_MUTE_TOOL_NAME,
            description="仅在你判断需要提前制止时开启禁言状态；目标和时长由程序固定。",
            parameters={
                "type": "object", "properties": {"reason": {"type": "string"}},
                "required": [], "additionalProperties": False,
            }, handler=plugin.qqbot_enable_poke_mute,
        ))
        mute_tool_attached = True
    req.func_tool.add_tool(FunctionTool(
        name=POKE_BACK_TOOL_NAME,
        description="反拍当前这次拍击者；目标由程序固定，不接受目标参数。",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=plugin.qqbot_poke_back,
    ))
    return mute_tool_attached


def _claim_poke_side_effect(event) -> str:
    if event.get_extra(POKE_SIDE_EFFECT_ATTEMPTED_EXTRA, ""):
        return "already_attempted"
    event.set_extra(POKE_SIDE_EFFECT_ATTEMPTED_EXTRA, "1")
    if event.is_private_chat() or str(event.get_extra(LLM_ROUTE_EXTRA, "") or "") != ROUTE_EXPLICIT:
        return "invalid_route"
    if not event.get_extra(POKE_INTERACTION_EXTRA, ""):
        return "not_poke"
    if not _poke_request_is_current(event):
        return "stale_generation"
    return ""


def _poke_request_is_current(event) -> bool:
    try:
        generation = int(event.get_extra(POKE_GENERATION_EXTRA, -1))
    except (TypeError, ValueError):
        return False
    return is_poke_request_current(
        event.get_group_id(),
        event.get_self_id(),
        expected_generation=generation,
    )


async def _mute_current_poker(event, *, source: str) -> tuple[bool, str]:
    group_id = event.get_group_id()
    self_id = str(event.get_self_id() or "").strip()
    sender_id = str(event.get_sender_id() or "").strip()
    if not can_mute_poker(group_id, self_id, sender_id):
        return False, "mute_rejected: sender_cooldown"
    if not try_claim_poke_mute(group_id, self_id, sender_id):
        return False, "mute_rejected: claim_busy"
    duration = pick_poke_mute_duration()
    try:
        call_action = getattr(getattr(event, "bot", None), "call_action", None)
        if not callable(call_action):
            raise RuntimeError("missing_bot_call_action")
        await call_action("set_group_ban", group_id=int(group_id), user_id=int(sender_id), duration=duration)
        mark_poke_mute_success(group_id, self_id, sender_id)
        logger.info("[TopicConcentration] poke mute success: source=%s group=%s self=%s sender=%s duration=%s", source, group_id, self_id, sender_id, duration)
        return True, f"mute_success: duration_seconds={duration}"
    except CancelledError:
        release_poke_mute_claim(group_id, self_id, sender_id)
        raise
    except Exception as exc:
        release_poke_mute_claim(group_id, self_id, sender_id)
        return False, f"mute_failed: {type(exc).__name__}"


def _maybe_attach_poke_mute_tool(plugin, event, req, *, poke_count: int) -> bool:
    return _attach_poke_tools(plugin, event, req, poke_count=poke_count)



def _candidate_request_is_current(event) -> bool:
    selected = str(event.get_extra(CURRENT_BOT_ID_EXTRA, "") or "")
    generation = int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0)
    queued_at = float(event.get_extra(CANDIDATE_QUEUED_AT_EXTRA, 0.0) or 0.0)
    return bool(event.get_extra(CANDIDATE_RESERVED_EXTRA, "")) and is_candidate_request_current(
        event.get_group_id(),
        selected,
        expected_generation=generation,
        queued_at=queued_at,
    )


def _stop_stale_candidate(event, *, stage: str) -> None:
    selected = str(event.get_extra(CURRENT_BOT_ID_EXTRA, "") or "")
    if event.get_extra(CANDIDATE_RESERVED_EXTRA, ""):
        event.set_extra(CANDIDATE_RESERVED_EXTRA, "")
    event.should_call_llm(True)
    event.stop_event()
    queued_at = float(event.get_extra(CANDIDATE_QUEUED_AT_EXTRA, 0.0) or 0.0)
    age = max(0.0, time.monotonic() - queued_at) if queued_at > 0 else -1.0
    logger.info(
        "[TopicConcentration] skip stale candidate: bot=%s group=%s stage=%s age=%.2fs max_wait=%.0fs generation=%s",
        selected,
        event.get_group_id(),
        stage,
        age,
        CANDIDATE_MAX_WAIT_SECONDS,
        int(event.get_extra(ACTIVATION_GENERATION_EXTRA, 0) or 0),
    )


async def _decide_named_call(context: Context, event, text: str) -> str | None:
    if not contains_cotton_candy_marker(text):
        return None
    local = classify_cotton_candy_call(text)
    if local == "call":
        return "named_call_local"
    if local == "non_call":
        logger.info(
            "[TopicConcentration] skip named call locally: group=%s text=%s",
            event.get_group_id(),
            _log_text(text),
        )
        return None
    response = await _chat_with_current_decision_provider(
        context=context,
        event=event,
        prompt=build_call_intent_prompt(text),
        session_id=f"topic_call_intent:{event.unified_msg_origin}",
        logger=logger,
    )
    if response is None:
        return None
    decision = parse_call_intent_response(getattr(response, "completion_text", "") or "")
    if decision is None:
        logger.info(
            "[TopicConcentration] skip named call: decision_parse_failed group=%s text=%s",
            event.get_group_id(),
            _log_text(text),
        )
        return None
    if not decision.should_reply:
        logger.info(
            "[TopicConcentration] skip named call by AI: group=%s reason=%s text=%s",
            event.get_group_id(),
            decision.reason,
            _log_text(text),
        )
        return None
    logger.info(
        "[TopicConcentration] allow named call by AI: group=%s reason=%s text=%s",
        event.get_group_id(),
        decision.reason,
        _log_text(text),
    )
    return "named_call_ai"


def _is_candidate_event(event, *, poke_target_id: str = "") -> bool:
    sender_id = str(event.get_sender_id() or "")
    if sender_id in KNOWN_SISTER_BOT_QQ_IDS:
        return False
    if str(event.get_self_id() or "") == sender_id:
        return False
    post_type = _event_post_type(event)
    if post_type and post_type != "message":
        return bool(poke_target_id)
    if event.is_private_chat():
        return True
    at_ids = _at_target_ids(event)
    self_id = str(event.get_self_id() or "")
    if self_id in at_ids:
        return True
    if set(at_ids) & KNOWN_SISTER_BOT_QQ_IDS:
        return False
    reply_target_id = _reply_target_id(event)
    if reply_target_id == self_id:
        return True
    if reply_target_id in KNOWN_SISTER_BOT_QQ_IDS:
        return False
    if getattr(event, "is_at_or_wake_command", False):
        return True
    if read_group_activation(event.get_group_id(), event.get_self_id()) is not None:
        return True
    return contains_cotton_candy_marker(_plain_text(event) or str(event.get_message_str() or ""))


def _plain_text(event) -> str:
    parts: list[str] = []
    for segment in event.get_messages():
        if isinstance(segment, Plain):
            parts.append(segment.text)
    return "".join(parts).strip()


def _at_target_ids(event) -> tuple[str, ...]:
    return tuple(str(segment.qq) for segment in event.get_messages() if isinstance(segment, At))


def _has_other_message_content(event) -> bool:
    for segment in event.get_messages():
        if isinstance(segment, At):
            continue
        if isinstance(segment, Plain) and not str(segment.text or "").strip():
            continue
        return True
    return False


def _reply_target_id(event) -> str:
    for segment in event.get_messages():
        if isinstance(segment, Reply):
            return str(segment.sender_id or "")
    return ""


def _response_text(response) -> str:
    text = str(getattr(response, "completion_text", "") or "").strip()
    if text:
        return text
    chain = getattr(response, "result_chain", None)
    if not chain:
        return ""
    parts: list[str] = []
    for item in chain:
        value = str(getattr(item, "text", "") or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()


def _resolve_qqbot_display_name(group_id: object, user_id: object) -> str:
    try:
        from astrbot_plugin_qqbot_features.main import resolve_display_name
    except ModuleNotFoundError:  # AstrBot runtime imports plugins as data.plugins.<name>.
        from data.plugins.astrbot_plugin_qqbot_features.main import resolve_display_name
    return str(resolve_display_name(group_id, user_id) or "").strip()


def _current_poke_text(event) -> str:
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    getter = getattr(raw, "get", None)
    try:
        raw_info = getter("raw_info") if callable(getter) else None
    except Exception:
        raw_info = None
    group_id = event.get_group_id()

    def resolve_for_group(user_id: str) -> str:
        try:
            return _resolve_qqbot_display_name(group_id, user_id)
        except Exception as exc:
            logger.warning(
                "[TopicConcentration] poke display name resolution failed: error_type=%s",
                type(exc).__name__,
            )
            return str(user_id or "").strip()

    rebuilt = rebuild_poke_display_text(raw_info, resolve_for_group)
    if rebuilt:
        return rebuilt
    display_name = resolve_for_group(str(event.get_sender_id() or ""))
    return f"{display_name}摸了摸你的头" if display_name else POKE_CALL_TEXT


def _current_poke_target_id(event) -> str:
    self_id = str(event.get_self_id() or "").strip()
    sender_id = str(event.get_sender_id() or "").strip()
    for segment in event.get_messages():
        if not isinstance(segment, Poke):
            continue
        target_reader = getattr(segment, "target_id", None)
        target_id = str(target_reader() if callable(target_reader) else getattr(segment, "id", "") or "").strip()
        if should_activate_from_poke(
            self_id=self_id,
            user_id=sender_id,
            target_id=target_id,
            bot_ids=(YUNQI_QQ,),
        ):
            return target_id
    return ""


def _event_post_type(event) -> str:
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    getter = getattr(raw, "get", None)
    if not callable(getter):
        return ""
    try:
        return str(getter("post_type") or "").strip()
    except Exception:
        return ""


def _apply_reply_control(response, cleaned_text: str, *, suppress: bool) -> None:
    if response is None:
        return
    if suppress:
        response.result_chain = None
        response.completion_text = ""
        response.reasoning_content = None
        response.reasoning_signature = None
        return
    response.completion_text = cleaned_text


def _log_text(text: str) -> str:
    return " ".join(str(text or "").split())[:80]
