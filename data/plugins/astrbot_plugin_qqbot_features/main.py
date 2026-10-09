from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import time
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event import filter
from astrbot.api.message_components import At, Image, Plain, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
from astrbot.core.star.filter.event_message_type import EventMessageType

from .bot_identity import KNOWN_SISTER_BOT_QQ_IDS
from .bot_identity import YUNQI_IDENTITY_FACT
from .bot_identity import is_known_bot_sender_id
from .codexradar_efficiency import fetch_codexradar_efficiency
from .codexradar_efficiency import render_codexradar_efficiency_image
from .comic_pdf import ComicPdfError
from .comic_pdf import ComicPdfService
from .comic_pdf import is_onebot_friend
from .comic_pdf import load_comic_pdf_config
from .comic_pdf import send_private_pdfs_with_password
from .draw_input import STANDARD_DRAW_PREFIX, doudouyan_command_parts, prepare_explicit_draw_request, preload_draw_references
from .draw_output import save_generated_image
from .draw_intent import DRAW_INTENT_SYSTEM, DrawIntentRouter, component_text
from .image_summary import prepare_onebot_image_summary_chain
from .image_summary import choose_image_summary
from .image_summary import random_summary_image_from_file
from .image_summary import random_summary_image_from_url
from .llm_error_guard import LLM_ERROR_NOTICE_COOLDOWN_SECONDS
from .llm_error_guard import LLM_ERROR_PREFIX
from .llm_error_guard import LlmErrorNoticeCooldown
from .llm_error_guard import build_llm_error_notice
from .group_nickname_store import GroupNicknameStore
from .menu_catalog import MENU_SECTIONS
from .menu_catalog import find_menu_section
from .menu_image import render_feature_menu_image
from .menu_image import render_overview_menu_image
from .meme_manager.commands import MEME_MANAGER_COMMAND_PATTERN
from .meme_manager.commands import looks_like_meme_manager_command
from .meme_manager.commands import parse_meme_manager_command
from .meme_manager.runtime import MemeManagerRuntime
from .onebot_api import OneBotCallApiAdapter
from .rightcodes_draw_logic import RightCodesDrawClient
from .rightcodes_draw_logic import RightCodesDrawQuotaStore
from .rightcodes_draw_logic import RightCodesDrawRequest
from .rightcodes_draw_logic import RightCodesDrawResult
from .rightcodes_draw_logic import extract_rightcodes_draw_model_switch
from .rightcodes_draw_logic import extract_removed_rightcodes_draw_temporary_model
from .rightcodes_draw_logic import format_draw_quota_exceeded_message
from .rightcodes_draw_logic import format_draw_start_message
from .rightcodes_draw_logic import format_rightcodes_draw_failure
from .rightcodes_draw_logic import format_rightcodes_draw_missing_prompt_message
from .rightcodes_draw_logic import format_rightcodes_draw_model_help
from .rightcodes_draw_logic import format_rightcodes_draw_model_switch_invalid
from .rightcodes_draw_logic import format_rightcodes_draw_model_switch_success
from .rightcodes_draw_logic import format_rightcodes_draw_points_mutation_denied
from .rightcodes_draw_logic import format_rightcodes_draw_points_ranking
from .rightcodes_draw_logic import format_rightcodes_draw_points_status
from .rightcodes_draw_logic import format_rightcodes_draw_success
from .rightcodes_draw_logic import format_rightcodes_draw_temporary_model_removed
from .rightcodes_draw_logic import format_rightcodes_draw_timeout
from .rightcodes_draw_logic import load_rightcodes_config
from .rightcodes_draw_logic import looks_like_rightcodes_draw_feature_request
from .rightcodes_draw_logic import looks_like_rightcodes_draw_help_command
from .rightcodes_draw_logic import looks_like_rightcodes_draw_invocation
from .rightcodes_draw_logic import looks_like_rightcodes_draw_model_switch
from .rightcodes_draw_logic import looks_like_rightcodes_draw_points_mutation_request
from .rightcodes_draw_logic import looks_like_rightcodes_draw_points_query
from .rightcodes_draw_logic import looks_like_rightcodes_draw_points_ranking
from .rightcodes_draw_logic import parse_rightcodes_draw_command
from .rightcodes_draw_logic import parse_rightcodes_draw_model_switch
from .rightcodes_draw_catalog import format_rightcodes_draw_catalog_injection
from .rightcodes_draw_catalog import should_inject_rightcodes_draw_catalog
from .rightcodes_draw_rewrite import RIGHTCODES_DRAW_REWRITE_SYSTEM_PROMPT
from .rightcodes_draw_rewrite import RightCodesDrawRewriteInput
from .rightcodes_draw_rewrite import build_rightcodes_draw_rewrite_prompt
from .rightcodes_draw_rewrite import format_rightcodes_draw_rewrite_failure
from .rightcodes_draw_rewrite import format_rightcodes_draw_rewrite_missing_context
from .rightcodes_draw_rewrite import merge_rewritten_draw_request
from .rightcodes_draw_rewrite import parse_rightcodes_draw_rewrite_response
from .rightcodes_draw_rewrite import should_rewrite_rightcodes_draw_prompt
from .request_context import build_current_request_context
from .request_context import collect_source_image_sources
from .request_context import extract_image_sources
from .request_context import extract_plain_text as extract_event_plain_text
from .request_context import format_source_messages
from .request_context import remove_empty_assistant_contexts
from .reread_state import RereadRepeatState
from .runtime_temp import TempDuplicateCleaner
from .runtime_temp import load_temp_dedupe_config
from .runtime_temp import resolve_astrbot_temp_root
from .runtime_temp import resolve_plugin_temp_dir
from .reply_style_guard_logic import CHAT_BUBBLE_REPLY_INSTRUCTION
from .reply_style_guard_logic import STYLE_IMMUTABILITY_INSTRUCTION
from .reply_style_guard_logic import normalize_long_input_tldr_threshold
from .reply_style_guard_logic import is_dangerous_local_tool_name
from .reply_style_guard_logic import normalize_fold_threshold
from .reply_style_guard_logic import recent_assistant_reply_texts
from .reply_style_guard_logic import sanitize_assistant_context_prompt_echoes
from .reply_style_guard_logic import sanitize_reply_plain_text
from .reply_style_guard_logic import should_disable_model_regex_segmenting
from .reply_style_guard_logic import should_reply_too_long_to_read
from .reply_style_guard_logic import split_chat_bubble_lines
from .reply_style_guard_logic import strip_internal_prompt_echo
from .reply_style_guard_runtime import build_folded_reply_chain
from .reply_style_guard_runtime import extract_onebot_source_tree
from .reply_style_guard_runtime import has_forward_message
from .social_events import GROUP_MEMBER_WELCOME_EXPRESSIONS
from .social_events import format_group_member_welcome
from .social_events import format_self_join_private_notice
from .social_events import should_send_member_welcome
from .source_knowledge import SourceIndex
from .source_knowledge import format_enabled_groups as format_source_enabled_groups
from .source_knowledge import format_source_injection
from .source_knowledge import load_source_knowledge_config
from .source_knowledge import resolve_domains
from .sub2api_usage import Sub2APIAccountSevenDayRanking
from .sub2api_usage import Sub2APIAccountUsage
from .sub2api_usage import Sub2APIClient
from .sub2api_usage import Sub2APIUsageAlert
from .sub2api_usage import Sub2APIUsageSnapshot
from .sub2api_usage import Sub2APIUserUsage
from .sub2api_usage import format_sub2api_usage_alert_message
from .sub2api_usage import format_sub2api_usage_response
from .sub2api_usage import load_sub2api_config
from .sub2api_usage import looks_like_sub2api_usage_command
from .sub2api_usage import parse_sub2api_usage_command
from .sub2api_usage import retain_failed_account_ranking
from .sub2api_usage import Sub2APIUsageCache
from .sub2api_usage import supports_sub2api_account_seven_day_ranking
from .sub2api_usage import update_sub2api_usage_alert_state
from .sub2api_usage_image import render_sub2api_usage_image

from astrbot.api.provider import LLMResponse
from astrbot.core.message.components import Plain as CorePlain
from astrbot.core.message.message_event_result import ResultContentType
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

FACTORIO_DOWNLOAD_PATTERN = (
    r"(?i)^.*(?:factorio|异星|太空时代|space\s*age|spaceage).*(?:下载|安装包).*(?:链接|地址)?$"
)
JMCOMIC_DOWNLOAD_PATTERN = r"(?i)^jm\s*([0-9]+)$"
MENU_PATTERN = r"^(?:菜单|帮助|指令)$"
FEATURE_MENU_PATTERN = r"^菜单\s*(?!\d+$)\S+$"
GROUP_FILE_CLEANUP_PATTERN = r"^(?:通知)?(?:大家|全员|群友)?(?:清理|整理)(?:群)?文件$|^(?:群)?文件(?:清理|整理)(?:通知)?$"
SUB2API_USAGE_PATTERN = r"(?i)^用量$"
LOLICON_ADMIN_PATTERN = r"^[开关](?:群色图|图片显示)$"
LOLICON_PATTERN = r"^(?:来点)?(?:[美色涩蛇]图|混合).*$"
ARC_RECOMMEND_PATTERN = r"^arctj\s*[0-9]+(?:\.[0-9]+)?$"
ARC_ACTIVITY_PATTERN = r"^arc(?:hd|tz)$"
ARC_APK_UPDATE_PATTERN = r"^(?:xz|arcxz)$"
ARC_GUESS_START_PATTERN = r"^(?:arczm|zm)(?:\s*[1-9][0-9]*)?$"
ARC_GUESS_ART_START_PATTERN = r"(?i)^(?:arcqh|qh)(?:\s*(?:[1-9][0-9]*|max))?$"
ARC_GUESS_ART_TILE_PATTERN = r"^arcqh\s*(?:bt|补图)$"
ARC_GUESS_REVEAL_PATTERN = r"^(?:arcjx|jx)$"
SHAPEZ_PATTERN = r"^(?:i|view|chart|chart1|chart2|path|path1|path2|p|puzzle|puzzle1|puzzle2) .*$"
KUN_PATTERN = (
    r"^(?:养鲲|摸鲲|抓鲲|捕鲲|属性|洗练.+[0-9]+|查看.*|等级排行(?:榜)?|财富排行(?:榜)?|"
    r"萌泪币排行(?:榜)?|金钱排行(?:榜)?|道具|背包|命名.+|商城|(?:购买|买|出售|卖).+|签到|"
    r"设置重置时间 *[0-9]+|[开关]新赛季提示|.*赠送.*|赠送全部 *[0-9]+|boss|Boss|查看boss|"
    r"查看Boss|查看boss属性|查看Boss属性|挑战|进击.*|(?:更改|修改).+[0-9]+)$"
)
SAKURA_PATTERN = (
    r"^(?:落樱之都|更新日志|玩法|注册.+|改名.+|个人信息|加经验[0-9]+|嘤[0-9]+|"
    r"恢复|回复|加[0-9]+(?:力量|智力|体质|敏捷|魅力))$"
)
FIXED_COMMAND_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        MENU_PATTERN,
        FEATURE_MENU_PATTERN,
        GROUP_FILE_CLEANUP_PATTERN,
        SUB2API_USAGE_PATTERN,
        FACTORIO_DOWNLOAD_PATTERN,
        JMCOMIC_DOWNLOAD_PATTERN,
        SHAPEZ_PATTERN,
        LOLICON_ADMIN_PATTERN,
        LOLICON_PATTERN,
        ARC_RECOMMEND_PATTERN,
        ARC_ACTIVITY_PATTERN,
        ARC_APK_UPDATE_PATTERN,
        ARC_GUESS_START_PATTERN,
        ARC_GUESS_ART_START_PATTERN,
        ARC_GUESS_ART_TILE_PATTERN,
        ARC_GUESS_REVEAL_PATTERN,
        MEME_MANAGER_COMMAND_PATTERN,
        KUN_PATTERN,
        SAKURA_PATTERN,
    )
)
FEATURE_MODE_FULL = "full"
OWNER_QQ = "605738729"
DEFAULT_LONG_REPLY_FOLD_THRESHOLD_CHARS = 300
DEFAULT_LONG_INPUT_TLDR_THRESHOLD_CHARS = 300
DEFAULT_LONG_INPUT_TLDR_TEXT = "太长不看喵"
LLM_STARTED_AT_EXTRA = "_qqbot_reply_style_guard_llm_started_at"
FORWARD_SOURCE_TREE_EXTRA = "qqbot_features_forward_source_tree"
MAX_FORWARD_IMAGE_ATTACHMENTS = 12
LLM_REQUEST_SESSION_EXTRA = "_qqbot_reply_style_guard_llm_request_session"
EMPTY_MENTION_CALL_EXTRA = "_qqbot_empty_mention_call"
GROUP_NICKNAME_CACHED_EXTRA = "_qqbot_group_nickname_cached"
INTERNAL_ERROR_PREFIXES = (
    "Error occurred while processing agent request:",
)
PLAIN_TEXT_REPLY_INSTRUCTION = (
    "本轮回复必须使用 QQ 纯文本聊天格式，不要使用 Markdown。"
    "以下文字格式要求只在决定发送文字时适用；拍一拍选择无视或反拍时，不要求补一条文字回复。"
    "禁止使用 # 标题、Markdown 列表符号、粗体、反引号代码块、引用块、Markdown 链接和表格。"
    "普通聊天优先短句自然表达，不要主动列项目符号；需要给 API、JSON、配置示例时允许保留换行和缩进，但不要包代码围栏。"
    "不要用“如果你愿意”“要的话”“你把具体内容发我”“我可以再帮你”等追问式收尾。"
    + STYLE_IMMUTABILITY_INSTRUCTION
    + CHAT_BUBBLE_REPLY_INSTRUCTION
)


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    aliases: tuple[str, ...] = ()
    status: str = "已移植"
    lines: tuple[str, ...] = ()


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="群管助手",
        aliases=("群管", "群管理", "群功能"),
        lines=(
            "通知清理文件：作者或机器人自身限定，统计超过一周的外层群文件并按大小禁言上传者",
        ),
    ),
    FeatureSpec(
        name="好友邀请处理",
        aliases=("好友申请", "邀请入群", "社交事件"),
        status="已移植",
        lines=(
            "收到好友申请或入群邀请时按配置自动同意，并记录处理结果",
            "机器人自身入群后私聊通知邀请者，群内不发自报消息",
        ),
    ),
    FeatureSpec(
        name="入群欢迎",
        aliases=("欢迎", "新人欢迎", "社交事件"),
        lines=("新成员入群时由云栖欢迎；已知姐妹机器人账号不会触发欢迎",),
    ),
    FeatureSpec(
        name="复读",
        aliases=("随机复读",),
        lines=("群里连续出现相同纯文本消息时概率复读，复读后短时间内冷却",),
    ),
    FeatureSpec(
        name="Lolicon美图",
        aliases=("Lolicon", "美图", "色图"),
        lines=(
            "来点美图 / 色图 / 混合：使用 AstrBot 迁移后的 Lolicon API、远程图片和元数据存储",
            "开群色图 / 关群色图：作者限定，控制当前群是否允许 R18",
            "开图片显示 / 关图片显示：作者限定，控制 R18 结果是否直接发图",
        ),
    ),
    FeatureSpec(
        name="养鲲",
        aliases=("鲲",),
        lines=(
            "摸鲲 / 养鲲 / 抓鲲 / 捕鲲：私聊创建或获取鲲",
            "属性 / 背包 / 商城 / 签到 / 挑战 / 排行 / 进击 / 赠送：使用 AstrBot 迁移后的存档与状态机",
        ),
    ),
    FeatureSpec(
        name="落樱之都",
        aliases=("樱花", "落樱"),
        status="基础玩法已移植",
        lines=("落樱之都 / 注册 / 改名 / 个人信息 / 加经验 / 嘤 / 加点 / 恢复：使用 AstrBot 迁移后的存档",),
    ),
    FeatureSpec(
        name="Arc",
        aliases=("Arc查询", "Arc狼人杀", "Arc吃鸡", "arcaea"),
        status="已移植",
        lines=(
            "arctj10.5：按 PTT 推荐谱面，使用本地 Arcaea 曲库和定数缓存",
            "archd / arctz：查看当前活动梯子",
            "zm / arczm：字母猜歌；qh / arcqh：曲绘猜歌；jx / arcjx：揭晓",
            "xz / arcxz：作者限定，查询并下载最新 c 版安装包",
            "后台：同步别名和定数缓存、过期猜歌会话、按日发送活动提醒",
        ),
    ),
    FeatureSpec(
        name="Factorio",
        aliases=("异星工厂", "太空时代", "Space Age", "spaceage"),
        lines=("Factorio下载链接 / 异星下载链接：获取 Space Age Windows 安装包下载链接",),
    ),
    FeatureSpec(
        name="异形工厂",
        aliases=("shapez",),
        lines=("i/view/chart/path：渲染 shapez 短代码图片；p/puzzle 在线谜题仍提示未配置 token",),
    ),
    FeatureSpec(
        name="RightCodes生图",
        aliases=("生图", "画图", "RightCodes"),
        lines=(
            "文生图 提示词 / 图生图 提示词（附图或引用）：40 积分/次",
            "头像生图 [@某人] 提示词：默认用自己的头像，指定目标须紧跟命令",
            "生图模型 / 生图价格：查看唯一模型与价格",
            "查看积分 / balance / points：查询积分、当前模型和消耗；积分排行：查看全群前 10",
        ),
    ),
    FeatureSpec(
        name="AI对话",
        aliases=("AI测试", "显式呼叫", "群聊激活"),
        status="使用 AstrBot 原生链路",
        lines=("AI 对话使用 AstrBot provider、persona、记忆、显式呼叫和群聊激活链路",),
    ),
)


@dataclass(frozen=True, slots=True)
class FactorioCredentials:
    username: str
    token: str


@dataclass(frozen=True, slots=True)
class FactorioDownloadLink:
    version: str
    url: str


@dataclass(frozen=True, slots=True)
class ShapezRenderResult:
    image_path: Path
    text: str


@dataclass(frozen=True, slots=True)
class LoliconRenderResult:
    prefix: str
    suffix: str
    image_path: Path | None = None
    image_url: str = ""
    image_text: str = ""


def get_runtime_db_root() -> Path:
    return get_qqbot_runtime_root() / "db"


def get_runtime_cache_root() -> Path:
    return get_plugin_temp_root("runtime-cache")


def get_astrbot_temp_root() -> Path:
    return resolve_astrbot_temp_root(fallback_data_root=get_astrbot_data_root())


def get_plugin_temp_root(name: str) -> Path:
    return resolve_plugin_temp_dir(
        fallback_data_root=get_astrbot_data_root(),
        name=name,
    )


@dataclass(frozen=True, slots=True)
class ArcRecommendationResult:
    text: str
    image_path: Path | None = None


class FactorioDownloadError(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


@register(
    "astrbot_plugin_qqbot_features",
    "MengLei",
    "棉花糖群务、互动、生图、游戏、LLM 上下文和回复守卫功能合集。",
    "0.15.3",
)
class QQBotFeaturesPlugin(Star):
    def __init__(self, context: Context, config=None):
        """Initialize shared feature runtimes and process-local coordination state."""
        super().__init__(context)
        self._feature_mode = read_feature_mode(config)
        self._auto_approve_friend_requests = read_bool_config(
            config,
            "auto_approve_friend_requests",
            default=True,
        )
        self._auto_approve_group_invites = read_bool_config(
            config,
            "auto_approve_group_invites",
            default=True,
        )
        self._reread_state = RereadRepeatState()
        self._llm_error_notice_cooldown = LlmErrorNoticeCooldown()
        self._arc_apk_update_manager = None
        self._rightcodes_config = load_rightcodes_config(config)
        self._comic_pdf_config = load_comic_pdf_config(config)
        self._comic_pdf_service = ComicPdfService(
            get_plugin_temp_root("jmcomic"),
            self._comic_pdf_config,
            cache_root=get_qqbot_runtime_root() / "comic_pdf_cache",
        )
        self._comic_active_request_count = 0
        self._comic_active_requests_lock = asyncio.Lock()
        self._meme_runtime = MemeManagerRuntime(
            self.context,
            ScopedPluginConfig(
                config,
                prefix="meme_manager",
            ),
        )
        self._sub2api_config = load_sub2api_config(config)
        self._sub2api_usage_cache = Sub2APIUsageCache()
        self._sub2api_refresh_task: asyncio.Task | None = None
        self._codexradar_efficiency_task: asyncio.Task | None = None
        self._codexradar_efficiency_image_path: Path | None = None
        self._arc_background_task: asyncio.Task | None = None
        temp_dedupe_config = load_temp_dedupe_config(config)
        self._temp_duplicate_cleaner = TempDuplicateCleaner(
            get_astrbot_temp_root(),
            temp_dedupe_config,
        )
        self._temp_duplicate_cleanup_task: asyncio.Task | None = None
        self._sub2api_alerted_thresholds_by_account: dict[str, set[int]] = {}
        self._rightcodes_draw_lock = asyncio.Semaphore(2)
        self._draw_intent_router = DrawIntentRouter()
        self._group_inviter_by_group_id: dict[str, str] = {}
        reply_style_guard_config = ScopedPluginConfig(
            config,
            prefix="reply_style_guard",
        )
        self._reply_long_reply_fold_threshold_chars = normalize_fold_threshold(
            get_config_value(
                reply_style_guard_config,
                "long_reply_fold_threshold_chars",
                DEFAULT_LONG_REPLY_FOLD_THRESHOLD_CHARS,
            ),
            default=DEFAULT_LONG_REPLY_FOLD_THRESHOLD_CHARS,
        )
        self._reply_disable_astrbot_segmented_reply = read_bool_config(
            reply_style_guard_config,
            "disable_astrbot_segmented_reply",
            default=True,
        )
        self._reply_long_input_tldr_threshold_chars = normalize_long_input_tldr_threshold(
            get_config_value(
                reply_style_guard_config,
                "long_input_tldr_threshold_chars",
                DEFAULT_LONG_INPUT_TLDR_THRESHOLD_CHARS,
            ),
            default=DEFAULT_LONG_INPUT_TLDR_THRESHOLD_CHARS,
        )
        self._reply_long_input_tldr_text = (
            str(
                get_config_value(
                    reply_style_guard_config,
                    "long_input_tldr_text",
                    DEFAULT_LONG_INPUT_TLDR_TEXT,
                )
                or DEFAULT_LONG_INPUT_TLDR_TEXT
            ).strip()
            or DEFAULT_LONG_INPUT_TLDR_TEXT
        )
        self._source_knowledge_config = load_source_knowledge_config(
            ScopedPluginConfig(
                config,
                prefix="source_knowledge",
            )
        )
        self._source_knowledge_index = SourceIndex(self._source_knowledge_config)
        self._install_aiocqhttp_error_guard()
        logger.info(
            "[QQBotFeatures] migrated feature plugin loaded, mode=%s auto_approve_friend=%s auto_approve_group_invite=%s",
            self._feature_mode,
            self._auto_approve_friend_requests,
            self._auto_approve_group_invites,
        )
        logger.info(
            "[QQBotFeatures] merged guards loaded: reply_fold_chars=%s disable_astrbot_segmented=%s long_input_tldr_chars=%s "
            "source_groups=%s source_roots=%s source_max_results=%s source_max_chars=%s "
            "source_max_files=%s source_max_file_bytes=%s",
            self._reply_long_reply_fold_threshold_chars,
            self._reply_disable_astrbot_segmented_reply,
            self._reply_long_input_tldr_threshold_chars,
            format_source_enabled_groups(self._source_knowledge_config.enabled_groups),
            len(self._source_knowledge_config.roots),
            self._source_knowledge_config.max_results,
            self._source_knowledge_config.max_chars,
            self._source_knowledge_config.max_files_per_domain,
            self._source_knowledge_config.max_file_bytes,
        )
        logger.info(
            "[QQBotFeatures] temp cleanup loaded: root=%s dedupe_enabled=%s interval=%s min_age=%s max_files=%s",
            self._temp_duplicate_cleaner.temp_root,
            temp_dedupe_config.enabled,
            temp_dedupe_config.interval_seconds,
            temp_dedupe_config.min_file_age_seconds,
            temp_dedupe_config.max_files_per_run,
        )

    async def initialize(self) -> None:
        if self._sub2api_config.base_url and self._sub2api_config.admin_api_key:
            self._sub2api_refresh_task = asyncio.create_task(self._sub2api_usage_refresh_loop())
            self._codexradar_efficiency_task = asyncio.create_task(
                self._codexradar_efficiency_refresh_loop()
            )
        self._arc_background_task = asyncio.create_task(self._arc_background_loop())
        self._temp_duplicate_cleanup_task = asyncio.create_task(
            self._temp_duplicate_cleaner.run(logger=logger)
        )

    async def terminate(self) -> None:
        await self._comic_pdf_service.shutdown()
        if self._temp_duplicate_cleanup_task is not None:
            await self._temp_duplicate_cleaner.stop()
            self._temp_duplicate_cleanup_task.cancel()
            try:
                await self._temp_duplicate_cleanup_task
            except asyncio.CancelledError:
                pass
        self._temp_duplicate_cleanup_task = None
        if self._sub2api_refresh_task is not None:
            self._sub2api_refresh_task.cancel()
            try:
                await self._sub2api_refresh_task
            except asyncio.CancelledError:
                pass
        self._sub2api_refresh_task = None
        if self._codexradar_efficiency_task is not None:
            self._codexradar_efficiency_task.cancel()
            try:
                await self._codexradar_efficiency_task
            except asyncio.CancelledError:
                pass
        self._codexradar_efficiency_task = None
        if self._arc_background_task is not None:
            self._arc_background_task.cancel()
            try:
                await self._arc_background_task
            except asyncio.CancelledError:
                pass
        self._arc_background_task = None
        await self._meme_runtime.terminate()

    @filter.event_message_type(
        EventMessageType.ALL,
        priority=900,
        desc="展开聊天记录第一层图片，交给 AstrBot 原生图片理解链路。",
    )
    async def expose_forward_images_to_astrbot(self, event: AstrMessageEvent):
        if not has_forward_message(event):
            return
        if not event.is_private_chat() and not getattr(event, "is_at_or_wake_command", False):
            return
        source_tree = await extract_onebot_source_tree(event)
        event.set_extra(FORWARD_SOURCE_TREE_EXTRA, source_tree)
        image_sources = collect_source_image_sources(
            source_tree,
            max_images=MAX_FORWARD_IMAGE_ATTACHMENTS,
        )
        if not image_sources:
            return
        existing_sources = set(extract_image_sources(event))
        appended = 0
        for source in image_sources:
            if source in existing_sources:
                continue
            image = (
                Image.fromURL(source)
                if source.startswith(("http://", "https://"))
                else Image(file=source)
            )
            event.message_obj.message.append(image)
            existing_sources.add(source)
            appended += 1
        if appended:
            logger.info(
                "[QQBotFeatures] exposed forwarded images to AstrBot: session=%s images=%s limit=%s",
                getattr(event, "unified_msg_origin", ""),
                appended,
                MAX_FORWARD_IMAGE_ATTACHMENTS,
            )

    @filter.on_llm_request(desc="在 LLM 请求前记录耗时、移除非主人私聊本机工具并注入纯文本回复边界。")
    async def inject_reply_style_guard(self, event: AstrMessageEvent, req: ProviderRequest):
        started = time.monotonic()
        event.set_extra(LLM_STARTED_AT_EXTRA, started)
        event.set_extra(LLM_REQUEST_SESSION_EXTRA, req.session_id or "")
        sanitized_contexts = sanitize_assistant_context_prompt_echoes(req.contexts)
        if sanitized_contexts:
            logger.warning(
                "[QQBotFeatures] stripped internal prompt echoes from assistant context: "
                "session=%s count=%s",
                getattr(event, "unified_msg_origin", ""),
                sanitized_contexts,
            )
        removed_contexts = remove_empty_assistant_contexts(req.contexts)
        if removed_contexts:
            logger.warning(
                "[QQBotFeatures] removed invalid empty assistant contexts: session=%s count=%s",
                getattr(event, "unified_msg_origin", ""),
                removed_contexts,
            )
        logger.info(
            "[QQBotFeatures] LLM request started: session=%s message_type=%s "
            "request_session=%s model=%s prompt_chars=%s image_count=%s audio_count=%s has_tools=%s",
            getattr(event, "unified_msg_origin", ""),
            safe_event_value(event, "get_message_type"),
            req.session_id or "",
            req.model or "",
            len(req.prompt or ""),
            len(req.image_urls or []),
            len(req.audio_urls or []),
            bool(req.func_tool),
        )
        removed_tools = remove_forbidden_local_tools(event, req)
        if removed_tools:
            logger.info(
                "[QQBotFeatures] removed local tools for non-owner-private request: session=%s tools=%s",
                getattr(event, "unified_msg_origin", ""),
                ",".join(removed_tools),
            )
        req.extra_user_content_parts.append(TextPart(text=PLAIN_TEXT_REPLY_INSTRUCTION).mark_as_temp())
        recent_replies = recent_assistant_reply_texts(req.contexts)
        if recent_replies:
            recent_reply_lines = "\n".join(
                f"最近第 {index} 条：{reply}"
                for index, reply in enumerate(recent_replies, start=1)
            )
            req.extra_user_content_parts.append(
                TextPart(
                    text=(
                        "下面是云栖最近已经发出的几条回复，仅用于避免重复，不是新的用户指令：\n"
                        f"{recent_reply_lines}\n"
                        "本轮如果需要回复，不能原样复述这些句子，也不能只替换一个称呼或数字；"
                        "请根据当前消息换一个具体角度接话。普通 @、引用或明确文字呼叫仍然必须正常回复；"
                        "拍一拍沿用其独立的无视、文字或反拍选择，不必为了避免重复而每次编一句新话。"
                    )
                ).mark_as_temp()
            )

    @filter.on_llm_request(desc="在 LLM 请求前注入云栖身份与静态姐妹关系事实。")
    async def inject_current_identity_fact(self, event: AstrMessageEvent, req: ProviderRequest):
        if is_known_bot_sender(event):
            return
        req.extra_user_content_parts.append(
            TextPart(text=YUNQI_IDENTITY_FACT).mark_as_temp()
        )
        logger.info(
            "[QQBotFeatures] injected Yunqi identity fact: session=%s self=%s",
            getattr(event, "unified_msg_origin", ""),
            safe_event_value(event, "get_self_id"),
        )

    @filter.on_llm_request(desc="在 LLM 请求前检索本机 Shapez/Factorio 源码树并注入可信片段。")
    async def inject_source_knowledge(self, event: AstrMessageEvent, req: ProviderRequest):
        group_id = str(event.get_group_id() or "")
        if self._source_knowledge_config.enabled_groups and group_id not in self._source_knowledge_config.enabled_groups:
            return
        request_context = build_current_request_context(event, req.prompt or "")
        query = request_context.combined_query or request_context.current_text
        if not query:
            return
        domains = tuple(
            domain
            for domain in resolve_domains(group_id, query)
            if domain in {"shapez", "factorio"}
        )
        if not domains:
            return
        results = self._source_knowledge_index.search(query, domains)
        if not results:
            logger.debug(
                "[QQBotFeatures] no source evidence: group=%s domains=%s query=%s",
                group_id,
                ",".join(domains),
                query[:80],
            )
            return
        injection = format_source_injection(results, query, self._source_knowledge_config.max_chars)
        if not injection:
            return
        req.extra_user_content_parts.append(TextPart(text=injection).mark_as_temp())
        logger.info(
            "[QQBotFeatures] injected source evidence: group=%s domains=%s results=%s chars=%s",
            group_id,
            ",".join(domains),
            len(results),
            len(injection),
        )

    @filter.on_llm_response(desc="记录 LLM 返回耗时，帮助区分上游仍在处理、已返回或已失败。")
    async def log_llm_response_latency(self, event: AstrMessageEvent, response: LLMResponse):
        raw_text = (getattr(response, "completion_text", "") or "") if response else ""
        cleaned_text = strip_internal_prompt_echo(raw_text)
        if response is not None and cleaned_text != raw_text:
            response.completion_text = cleaned_text
            logger.warning(
                "[QQBotFeatures] stripped internal prompt echo from LLM response: "
                "session=%s original_chars=%s visible_chars=%s",
                getattr(event, "unified_msg_origin", ""),
                len(raw_text),
                len(cleaned_text),
            )
        started = event.get_extra(LLM_STARTED_AT_EXTRA)
        elapsed = time.monotonic() - started if isinstance(started, (int, float)) else -1.0
        logger.info(
            "[QQBotFeatures] LLM response returned: session=%s request_session=%s "
            "elapsed=%.2fs has_text=%s has_chain=%s has_tool_call=%s has_reasoning=%s is_chunk=%s",
            getattr(event, "unified_msg_origin", ""),
            event.get_extra(LLM_REQUEST_SESSION_EXTRA, ""),
            elapsed,
            bool((getattr(response, "completion_text", "") or "").strip()) if response else False,
            bool(getattr(response, "result_chain", None)) if response else False,
            bool(getattr(response, "tools_call_args", None)) if response else False,
            bool((getattr(response, "reasoning_content", "") or "").strip()) if response else False,
            bool(getattr(response, "is_chunk", False)) if response else False,
        )
        await self._meme_runtime.resp(event, response)

    @filter.on_decorating_result(desc="发送前拦截群聊 LLM 内部错误，并清理普通回复风格。")
    async def strip_reply_style_tail(self, event: AstrMessageEvent):
        """Suppress group LLM failures before applying ordinary reply decorations."""
        result = event.get_result()
        if result is None or not result.chain:
            return
        if await self._handle_group_llm_error(event, result):
            return
        started = event.get_extra(LLM_STARTED_AT_EXTRA)
        if isinstance(started, (int, float)):
            logger.info(
                "[QQBotFeatures] decorating reply result: session=%s request_session=%s "
                "elapsed=%.2fs chain_items=%s",
                getattr(event, "unified_msg_origin", ""),
                event.get_extra(LLM_REQUEST_SESSION_EXTRA, ""),
                time.monotonic() - started,
                len(result.chain),
            )
        changed = False
        if hasattr(result, "use_markdown"):
            result.use_markdown(False)
        cleaned_chain = []
        for comp in result.chain:
            if not isinstance(comp, CorePlain):
                cleaned_chain.append(comp)
                continue
            cleaned = sanitize_reply_plain_text(
                comp.text,
                strip_question_tail=not bool(event.get_extra(EMPTY_MENTION_CALL_EXTRA, "")),
            )
            if cleaned != comp.text:
                comp.text = cleaned
                changed = True
            if cleaned:
                cleaned_chain.append(comp)
        if changed:
            result.chain = cleaned_chain
            logger.info(
                "[QQBotFeatures] sanitized reply style: session=%s",
                getattr(event, "unified_msg_origin", ""),
            )
        bubbled = self._split_short_chat_bubble_result(event, result)
        if bubbled:
            logger.info(
                "[QQBotFeatures] split model-declared chat bubble lines: session=%s lines=%s",
                getattr(event, "unified_msg_origin", ""),
                bubbled,
            )
        folded = self._fold_long_reply_result(event, result)
        if folded:
            logger.info(
                "[QQBotFeatures] folded long reply into AstrBot Nodes chain: session=%s",
                getattr(event, "unified_msg_origin", ""),
            )
        if not bubbled and _should_disable_segmented_reply_for_result(
            self.context,
            result,
            override_enabled=self._reply_disable_astrbot_segmented_reply,
        ):
            result.set_result_content_type(ResultContentType.GENERAL_RESULT)
            logger.info(
                "[QQBotFeatures] plugin override disabled AstrBot segmented reply for LLM result: session=%s",
                getattr(event, "unified_msg_origin", ""),
            )
        await self._meme_runtime.on_decorating_result(event)

    async def _handle_group_llm_error(self, event: AstrMessageEvent, result) -> bool:
        """Clear a Core LLM group error and privately notify the owner when eligible."""
        if event.is_private_chat():
            return False
        if getattr(result, "result_content_type", None) not in (
            ResultContentType.GENERAL_RESULT,
            ResultContentType.AGENT_RUNNER_ERROR,
        ):
            return False
        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            return False
        self_id = str(event.get_self_id() or "").strip()
        notice = build_llm_error_notice(
            _plain_result_text(result.chain),
            self_id=self_id,
            group_id=group_id,
        )
        if notice is None:
            return False

        event.clear_result()
        if not self._llm_error_notice_cooldown.claim(notice.key):
            logger.info(
                "[QQBotFeatures] suppressed duplicate group LLM error: self_id=%s group_id=%s category=%s",
                self_id,
                group_id,
                notice.category,
            )
            return True

        try:
            await AstrBotOneBotApi(event).call_api(
                "send_private_msg",
                user_id=int(OWNER_QQ),
                message=notice.message,
            )
        except Exception as exc:
            logger.error(
                "[QQBotFeatures] failed to notify owner about group LLM error: "
                "self_id=%s group_id=%s category=%s notify_error_type=%s",
                self_id,
                group_id,
                notice.category,
                type(exc).__name__,
            )
            return True

        logger.info(
            "[QQBotFeatures] notified owner about group LLM error: "
            "self_id=%s group_id=%s owner=%s category=%s cooldown_seconds=%.0f",
            self_id,
            group_id,
            OWNER_QQ,
            notice.category,
            LLM_ERROR_NOTICE_COOLDOWN_SECONDS,
        )
        return True

    @filter.after_message_sent(desc="发送后补发未混入同一消息链的本地表情图片，并清理临时文件。")
    async def meme_manager_after_message_sent(self, event: AstrMessageEvent):
        await self._meme_runtime.after_message_sent(event)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=2000, desc="直接叫到 bot 的群聊长消息短路回复。")
    async def handle_too_long_direct_group_message(self, event: AstrMessageEvent):
        if not _should_reply_too_long_to_read_event(
            event,
            threshold=self._reply_long_input_tldr_threshold_chars,
        ):
            return
        yield event.plain_result(self._reply_long_input_tldr_text)
        event.stop_event()

    @filter.event_message_type(
        EventMessageType.PRIVATE_MESSAGE,
        priority=800,
        desc="私聊聊天记录无法展开任何文字或图片时给出明确提示。",
    )
    async def handle_unreadable_private_forward(self, event: AstrMessageEvent):
        if not has_forward_message(event):
            return
        if is_known_bot_sender(event):
            return
        cached_source_tree = event.get_extra(FORWARD_SOURCE_TREE_EXTRA)
        source_tree = cached_source_tree if isinstance(cached_source_tree, tuple) else ()
        if format_source_messages(source_tree) or collect_source_image_sources(
            source_tree,
            max_images=MAX_FORWARD_IMAGE_ATTACHMENTS,
        ):
            return
        logger.warning(
            "[QQBotFeatures] private forward message has no readable content: session=%s sender=%s",
            getattr(event, "unified_msg_origin", ""),
            event.get_sender_id(),
        )
        yield event.plain_result("这条折叠消息我读不到内容。")
        event.stop_event()

    def _install_aiocqhttp_error_guard(self) -> None:
        """Install final OneBot suppression for internal errors and image summaries."""
        if getattr(AiocqhttpMessageEvent, "_runtime_guard_installed", False):
            logger.info("[QQBotFeatures] aiocqhttp error guard already installed")
            return

        original_send_message = AiocqhttpMessageEvent.send_message

        async def guarded_send_message(
            cls,
            bot,
            message_chain,
            event=None,
            is_group: bool = False,
            session_id: str | None = None,
        ) -> None:
            """Suppress leaked internal text before delegating ordinary OneBot sends."""
            text = _plain_message_chain_text(message_chain)
            internal_agent_error = any(
                text.startswith(prefix) for prefix in INTERNAL_ERROR_PREFIXES
            )
            group_llm_error = is_group and text.startswith(LLM_ERROR_PREFIX)
            if internal_agent_error or group_llm_error:
                logger.error(
                    "[QQBotFeatures] suppressed internal error from user output: "
                    "kind=%s session_id=%s is_group=%s message_chars=%s",
                    "group_llm" if group_llm_error else "internal_agent",
                    session_id,
                    is_group,
                    len(text),
                )
                return
            message_chain = await prepare_onebot_image_summary_chain(message_chain)
            await original_send_message.__func__(
                cls,
                bot,
                message_chain,
                event=event,
                is_group=is_group,
                session_id=session_id,
            )

        AiocqhttpMessageEvent.send_message = classmethod(guarded_send_message)
        AiocqhttpMessageEvent._runtime_guard_installed = True
        logger.info(
            "[QQBotFeatures] aiocqhttp send guard installed: "
            "internal_errors=true group_llm_errors=true image_summary=true"
        )

    def _fold_long_reply_result(self, event: AstrMessageEvent, result) -> bool:
        if self._reply_long_reply_fold_threshold_chars <= 0:
            return False
        if event.get_platform_name() != "aiocqhttp":
            return False
        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            return False
        if result is None or not result.is_model_result():
            return False
        text = _plain_result_text(result.chain)
        folded = build_folded_reply_chain(
            text,
            threshold=self._reply_long_reply_fold_threshold_chars,
            uin=safe_event_value(event, "get_self_id") or "10000",
            name=read_bot_display_name(event),
        )
        if folded is None:
            return False
        result.chain = folded.chain
        result.set_result_content_type(ResultContentType.GENERAL_RESULT)
        logger.info(
            "[QQBotFeatures] folded long reply: session=%s chars=%s nodes=%s via_core_chain=true",
            getattr(event, "unified_msg_origin", ""),
            folded.text_chars,
            folded.node_count,
        )
        return True

    def _split_short_chat_bubble_result(self, event: AstrMessageEvent, result) -> int:
        if result is None or not result.is_model_result():
            return 0
        if event.is_private_chat():
            return 0
        if len(result.chain) != 1:
            return 0
        comp = result.chain[0]
        if not isinstance(comp, CorePlain):
            return 0
        lines = split_chat_bubble_lines(comp.text)
        if len(lines) <= 1:
            return 0
        result.chain = [CorePlain(line) for line in lines]
        return len(lines)

    @filter.regex(MENU_PATTERN, desc="发送总览图片菜单，展示当前 AstrBot 已接管的群务、互动、生图、游戏和工具分类。")
    async def menu(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="menu_overview"):
            return
        try:
            image_path = render_overview_menu_image(
                features=MENU_SECTIONS,
                feature_mode=self._feature_mode,
                output_dir=get_menu_image_cache_root(),
            )
            yield event.chain_result([random_summary_image_from_file(image_path)])
        except Exception as exc:
            logger.exception("[QQBotFeatures] failed to render overview menu image: %s", exc)
            yield event.plain_result(build_menu_text(self._feature_mode))
        event.stop_event()

    @filter.regex(FEATURE_MENU_PATTERN, desc="发送指定分类的图片菜单，例如“菜单棉花糖互动”“菜单Arcaea”。")
    async def feature_menu(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="menu_feature"):
            return
        key = re.sub(r"^菜单\s*", "", event.get_message_str().strip(), count=1)
        menu_item = find_menu_section(key) or find_feature(key)
        if menu_item is None:
            yield event.plain_result("没有这个模块哦！")
            event.stop_event()
            return
        try:
            image_path = render_feature_menu_image(
                feature=menu_item,
                feature_mode=self._feature_mode,
                output_dir=get_menu_image_cache_root(),
            )
            yield event.chain_result([random_summary_image_from_file(image_path)])
        except Exception as exc:
            logger.exception("[QQBotFeatures] failed to render feature menu image: %s", exc)
            yield event.plain_result(build_feature_menu_text(menu_item))
        event.stop_event()

    @filter.event_message_type(EventMessageType.ALL, desc="统一表情管理固定指令入口，例如“表情管理 开启管理后台”。")
    async def meme_manager_command(self, event: AstrMessageEvent):
        text = extract_plain_text(event).strip()
        command = parse_meme_manager_command(text)
        if command is None:
            return
        if not _should_handle_migrated_command(
            event,
            self._feature_mode,
            command_type=f"meme_manager:{command.action}",
        ):
            return
        async for result in self._meme_runtime.handle_command(
            event,
            command,
            is_admin=is_bot_admin_or_self(event),
        ):
            yield result
        event.stop_event()

    @filter.event_message_type(EventMessageType.ALL, desc="表情管理添加表情后的图片上传等待入口。")
    async def meme_manager_upload_image(self, event: AstrMessageEvent):
        handled = False
        async for result in self._meme_runtime.handle_upload_image(event):
            handled = True
            yield result
        if handled:
            event.stop_event()

    @filter.platform_adapter_type("aiocqhttp")
    @filter.regex(GROUP_FILE_CLEANUP_PATTERN, desc="群文件清理通知命令，作者或机器人自身可触发，用于扫描并提醒清理超期外层群文件。")
    async def group_file_cleanup(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="group_cleanup"):
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("群文件清理只能在群聊中使用。")
            event.stop_event()
            return
        if not is_bot_admin_or_self(event):
            return
        if not is_migrated_plugin_enabled("group_assistant"):
            return
        try:
            await run_group_file_cleanup(event)
        except Exception as exc:
            yield event.plain_result(f"群文件清理失败：{exc}")
        event.stop_event()

    @filter.platform_adapter_type("aiocqhttp")
    @filter.regex(JMCOMIC_DOWNLOAD_PATTERN, desc="下载 JM 作品、缓存明文 PDF，并私聊发送密码加密副本。")
    async def jmcomic_download(self, event: AstrMessageEvent):
        text = extract_plain_text(event).strip()
        match = re.fullmatch(JMCOMIC_DOWNLOAD_PATTERN, text)
        if match is None:
            return
        album_id = match.group(1)
        sender_id = str(event.get_sender_id() or "").strip()
        if not sender_id.isdigit() or is_known_bot_sender_id(sender_id):
            return
        api = AstrBotOneBotApi(event)
        try:
            current_is_friend = await is_onebot_friend(api, int(sender_id))
        except Exception as exc:
            logger.warning(
                "[QQBotFeatures] JM friend lookup failed: self=%s user=%s error_type=%s",
                event.get_self_id(),
                sender_id,
                type(exc).__name__,
            )
            current_is_friend = False

        has_friend = current_is_friend
        if not has_friend:
            yield event.plain_result("需要先添加云栖为好友，再重新发送。")
            event.stop_event()
            return
        if not self._comic_pdf_config.enabled:
            yield event.plain_result("JM 下载功能当前未启用。")
            event.stop_event()
            return

        async with self._comic_active_requests_lock:
            request_capacity = (
                self._comic_pdf_config.max_concurrent_jobs
                + self._comic_pdf_config.max_queued_jobs
            )
            if self._comic_active_request_count >= request_capacity:
                request_accepted = False
            else:
                self._comic_active_request_count += 1
                request_accepted = True
        if not request_accepted:
            yield event.plain_result("JM 下载队列已满，请稍后再试。")
            event.stop_event()
            return

        delivery = None
        try:
            submission = await self._comic_pdf_service.submit(album_id)
            estimate_low, estimate_high = _comic_download_estimate_minutes(
                submission.queue_position,
                self._comic_pdf_config.max_concurrent_jobs,
            )
            status_text = {
                "cache_hit": f"JM{album_id} 缓存命中，开始处理。",
                "started": (
                    f"JM{album_id} 开始下载，预计约 {estimate_low}-{estimate_high} 分钟完成。"
                ),
                "shared": (
                    f"JM{album_id} 正在下载，已加入等待"
                    + (
                        f"，当前排队第 {submission.queue_position} 个"
                        if submission.queue_position > 0
                        else ""
                    )
                    + f"，预计约 {estimate_low}-{estimate_high} 分钟完成。"
                ),
                "queued": (
                    f"JM{album_id} 开始下载，当前排队第 {submission.queue_position} 个，"
                    f"预计约 {estimate_low}-{estimate_high} 分钟完成。"
                ),
            }.get(submission.status, f"JM{album_id} 开始处理。")
            yield event.plain_result(status_text)
            cache_entry = await submission.wait()
            if not await is_onebot_friend(api, int(sender_id)):
                raise ComicPdfError("发送前检测到好友关系已失效，请重新添加好友后再试。")
            delivery = await self._comic_pdf_service.create_delivery(cache_entry)
            await send_private_pdfs_with_password(
                api,
                int(sender_id),
                album_id,
                delivery.artifacts,
                title=cache_entry.title,
                author=cache_entry.author,
                tags=cache_entry.tags,
            )
        except ComicPdfError as exc:
            yield event.plain_result(str(exc))
        except Exception as exc:
            logger.error(
                "[QQBotFeatures] JM PDF task failed: album_id=%s user=%s error_type=%s",
                album_id,
                sender_id,
                type(exc).__name__,
            )
            yield event.plain_result("JM 下载、加密或私聊文件发送失败，请稍后重试。")
        finally:
            if delivery is not None:
                await asyncio.to_thread(delivery.cleanup)
            async with self._comic_active_requests_lock:
                self._comic_active_request_count = max(
                    0,
                    self._comic_active_request_count - 1,
                )
        event.stop_event()

    @filter.regex(FACTORIO_DOWNLOAD_PATTERN, desc="获取 Factorio Space Age Windows 安装包下载链接，需要本机已配置 Factorio 凭据。")
    async def factorio_download(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="factorio_download"):
            return
        try:
            stable_link, experimental_link = await asyncio.to_thread(
                fetch_factorio_space_age_windows_links
            )
        except FactorioDownloadError as exc:
            yield event.plain_result(f"Factorio: 没获取到 Space Age Windows 下载链接：{exc}")
            event.stop_event()
            return
        yield event.plain_result(
            f"Factorio: Space Age Windows 稳定版 {stable_link.version} 下载链接：\n"
            f"{stable_link.url}\n\n"
            f"Factorio: Space Age Windows 测试版 {experimental_link.version} 下载链接：\n"
            f"{experimental_link.url}"
        )
        event.stop_event()

    @filter.regex(SUB2API_USAGE_PATTERN, desc="查询全部 Sub2API 账号额度和消费榜，并在末尾附加后台缓存的 CodexRadar 智力效率图。")
    async def sub2api_usage(self, event: AstrMessageEvent):
        text = extract_plain_text(event).strip()
        command = parse_sub2api_usage_command(text)
        if command is None:
            return
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="sub2api_usage"):
            return
        snapshot = self._get_cached_sub2api_usage()
        if snapshot is None:
            yield event.plain_result("Sub2API 用量后台刷新中，暂无可用缓存；稍后再发“用量”即可直接返回当前值。")
            event.stop_event()
            return
        try:
            image_path = render_sub2api_usage_image(
                snapshot=snapshot,
                output_dir=get_sub2api_usage_image_cache_root(),
            )
            chain = [random_summary_image_from_file(image_path)]
            codexradar_path = self._codexradar_efficiency_image_path
            if codexradar_path is None or not codexradar_path.is_file():
                try:
                    codexradar_snapshot = await asyncio.to_thread(fetch_codexradar_efficiency)
                    codexradar_path = await asyncio.to_thread(
                        render_codexradar_efficiency_image,
                        snapshot=codexradar_snapshot,
                        output_dir=get_codexradar_efficiency_image_cache_root(),
                    )
                    self._codexradar_efficiency_image_path = codexradar_path
                except Exception as codexradar_exc:
                    logger.warning(
                        "[QQBotFeatures] failed to recover CodexRadar efficiency image for usage command: %s",
                        codexradar_exc,
                    )
            if codexradar_path is not None and codexradar_path.is_file():
                chain.append(random_summary_image_from_file(codexradar_path))
            yield event.chain_result(chain)
        except Exception as exc:
            logger.exception("[QQBotFeatures] failed to render Sub2API usage image: %s", exc)
            yield event.plain_result(format_sub2api_usage_response(snapshot))
        event.stop_event()

    def _get_cached_sub2api_usage(self) -> Sub2APIUsageSnapshot | None:
        return self._sub2api_usage_cache.get_latest()

    def _new_sub2api_client(self) -> Sub2APIClient:
        return Sub2APIClient(
            base_url=self._sub2api_config.base_url,
            admin_api_key=self._sub2api_config.admin_api_key,
            timeout_seconds=self._sub2api_config.timeout_seconds,
        )

    async def _refresh_sub2api_account_ranking(
        self,
        account: Sub2APIAccountUsage,
        users: tuple[Sub2APIUserUsage, ...],
        previous: Sub2APIAccountSevenDayRanking | None,
        *,
        now: datetime,
    ) -> Sub2APIAccountSevenDayRanking:
        """Refresh one account atomically, retaining only that account's stale cache."""
        last_error = ""
        for _ in range(2):
            try:
                ranking_users = await self._new_sub2api_client().get_account_seven_day_ranking(
                    account,
                    users,
                    now=now,
                )
                return Sub2APIAccountSevenDayRanking(
                    account_id=account.account_id,
                    users=ranking_users,
                    refreshed_at=datetime.now(timezone.utc),
                )
            except Exception as exc:
                last_error = str(exc)
        return retain_failed_account_ranking(
            account.account_id,
            previous,
            last_error,
        )

    async def _refresh_sub2api_users_once(self) -> Sub2APIUsageSnapshot:
        """Refresh global rolling user costs without changing per-account rankings."""
        previous = self._sub2api_usage_cache.get_latest()
        accounts = previous.accounts if previous is not None else ()
        account_rankings = previous.account_seven_day_rankings if previous is not None else ()
        users = previous.users if previous is not None else ()
        accounts_refreshed_at = previous.accounts_refreshed_at if previous is not None else None
        users_refreshed_at = previous.users_refreshed_at if previous is not None else None
        accounts_error = previous.accounts_error if previous is not None else ""
        users_error = ""
        try:
            users = tuple(await self._new_sub2api_client().get_user_usage_ranking())
            users_refreshed_at = datetime.now(timezone.utc)
        except Exception:
            try:
                # 用户榜由多个只读趋势请求拼合；上游短暂失败时立即完整重试一次。
                users = tuple(await self._new_sub2api_client().get_user_usage_ranking())
                users_refreshed_at = datetime.now(timezone.utc)
            except Exception as exc:
                users_error = str(exc)
        snapshot = Sub2APIUsageSnapshot(
            accounts=accounts,
            account_seven_day_rankings=account_rankings,
            users=users,
            accounts_refreshed_at=accounts_refreshed_at,
            users_refreshed_at=users_refreshed_at,
            accounts_error=accounts_error,
            users_error=users_error,
        )
        self._sub2api_usage_cache.set(snapshot)
        return snapshot

    async def _refresh_sub2api_accounts_once(self) -> Sub2APIUsageSnapshot:
        """Refresh account quotas and each account's cycle ranking independently."""
        previous = self._sub2api_usage_cache.get_latest()
        accounts = previous.accounts if previous is not None else ()
        account_rankings = previous.account_seven_day_rankings if previous is not None else ()
        users = previous.users if previous is not None else ()
        accounts_refreshed_at = previous.accounts_refreshed_at if previous is not None else None
        users_refreshed_at = previous.users_refreshed_at if previous is not None else None
        accounts_error = ""
        users_error = previous.users_error if previous is not None else ""
        try:
            accounts = tuple(await self._new_sub2api_client().get_account_usage(force_refresh=True))
            accounts_refreshed_at = datetime.now(timezone.utc)
        except Exception:
            try:
                # 账号列表等整轮请求遇到一次瞬时网络错误时，完整重试一轮。
                accounts = tuple(await self._new_sub2api_client().get_account_usage(force_refresh=True))
                accounts_refreshed_at = datetime.now(timezone.utc)
            except Exception as exc:
                accounts_error = str(exc)
        if not accounts_error:
            previous_by_account = {
                ranking.account_id: ranking
                for ranking in account_rankings
            }
            ranking_now = datetime.now(timezone.utc)
            refreshed_rankings: list[Sub2APIAccountSevenDayRanking] = []
            for account in accounts:
                if not supports_sub2api_account_seven_day_ranking(account):
                    continue
                refreshed_rankings.append(
                    await self._refresh_sub2api_account_ranking(
                        account,
                        users,
                        previous_by_account.get(account.account_id),
                        now=ranking_now,
                    )
                )
            account_rankings = tuple(refreshed_rankings)
        snapshot = Sub2APIUsageSnapshot(
            accounts=accounts,
            account_seven_day_rankings=account_rankings,
            users=users,
            accounts_refreshed_at=accounts_refreshed_at,
            users_refreshed_at=users_refreshed_at,
            accounts_error=accounts_error,
            users_error=users_error,
        )
        self._sub2api_usage_cache.set(snapshot)
        return snapshot

    async def _sub2api_usage_refresh_loop(self) -> None:
        interval = self._sub2api_config.refresh_interval_seconds
        phase_interval = max(30.0, interval / 2)
        while True:
            try:
                snapshot = await self._refresh_sub2api_users_once()
                logger.info(
                    "[QQBotFeatures] refreshed Sub2API user usage cache, users=%s interval=%ss users_error=%s",
                    len(snapshot.users),
                    interval,
                    bool(snapshot.users_error),
                )
                await asyncio.sleep(phase_interval)
                snapshot = await self._refresh_sub2api_accounts_once()
                if not snapshot.accounts_error:
                    await self._send_sub2api_usage_alerts(
                        update_sub2api_usage_alert_state(
                            list(snapshot.accounts),
                            self._sub2api_alerted_thresholds_by_account,
                        )
                    )
                account_ranking_errors = sum(
                    1 for ranking in snapshot.account_seven_day_rankings if ranking.error
                )
                logger.info(
                    "[QQBotFeatures] refreshed Sub2API account usage cache, accounts=%s users=%s interval=%ss account_error=%s users_error=%s account_7d_errors=%s",
                    len(snapshot.accounts),
                    len(snapshot.users),
                    interval,
                    bool(snapshot.accounts_error),
                    bool(snapshot.users_error),
                    account_ranking_errors,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[QQBotFeatures] failed to refresh Sub2API usage cache: %s", exc)
            await asyncio.sleep(phase_interval)

    async def _codexradar_efficiency_refresh_loop(self) -> None:
        """Refresh the optional public CodexRadar panel without delaying commands."""
        while True:
            try:
                snapshot = await asyncio.to_thread(fetch_codexradar_efficiency)
                self._codexradar_efficiency_image_path = await asyncio.to_thread(
                    render_codexradar_efficiency_image,
                    snapshot=snapshot,
                    output_dir=get_codexradar_efficiency_image_cache_root(),
                )
                logger.info(
                    "[QQBotFeatures] refreshed CodexRadar efficiency cache, points=%s runs_24h=%s",
                    len(snapshot.points),
                    snapshot.runs_24h_total,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[QQBotFeatures] failed to refresh CodexRadar efficiency cache: %s", exc)
            await asyncio.sleep(300)

    async def _send_sub2api_usage_alerts(self, alerts: list[Sub2APIUsageAlert]) -> None:
        if not alerts or not self._sub2api_config.alert_group_ids:
            return
        bot = self._get_onebot_bot()
        if bot is None:
            logger.warning("[QQBotFeatures] skip Sub2API usage alert because no aiocqhttp bot is connected")
            return
        for alert in alerts:
            message = format_sub2api_usage_alert_message(alert)
            for group_id in self._sub2api_config.alert_group_ids:
                try:
                    await bot.call_action(
                        "send_group_msg",
                        group_id=int(group_id),
                        message=message,
                    )
                except Exception as exc:
                    logger.warning(
                        "[QQBotFeatures] failed to send Sub2API usage alert: group_id=%s threshold=%s error=%s",
                        group_id,
                        alert.threshold,
                        exc,
                    )

    async def _arc_background_loop(self) -> None:
        service = None
        while True:
            try:
                if service is None:
                    service = build_arc_background_service()
                bot = self._get_onebot_bot()
                if bot is not None:
                    await service.run_once(OneBotCallApiAdapter(bot))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[QQBotFeatures] Arc background loop failed: %s", exc)
            await asyncio.sleep(60)

    def _get_onebot_bot(self):
        for platform in getattr(self.context.platform_manager, "platform_insts", []):
            if getattr(platform.meta(), "name", "") != "aiocqhttp":
                continue
            bot = getattr(platform, "bot", None)
            if bot is not None:
                return bot
        return None

    @filter.regex(SHAPEZ_PATTERN, desc="渲染异形工厂 shapez 短代码、结构图或路径图；在线谜题在未配置 token 时给出提示。")
    async def shapez_render(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="shapez_render"):
            return
        text = event.get_message_str().strip()
        command, _, argument = text.partition(" ")
        command = command.lower()
        if command in {"p", "puzzle", "puzzle1", "puzzle2"}:
            yield event.plain_result("没获取到 shapez 谜题：在线谜题下载需要 shapez 登录 token，当前未配置。")
            event.stop_event()
            return
        try:
            result = await asyncio.to_thread(render_shapez_command, command, argument)
        except Exception as exc:
            yield event.plain_result(f"shapez 渲染失败：{exc}")
            event.stop_event()
            return
        chain = [random_summary_image_from_file(result.image_path), Plain(result.text)]
        yield event.chain_result(chain)
        event.stop_event()

    @filter.regex(LOLICON_ADMIN_PATTERN, desc="作者限定的 Lolicon 群配置命令，用于开关群 R18 和图片直发显示。")
    async def lolicon_admin(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="lolicon_admin"):
            return
        if str(event.get_sender_id()) != get_qqbot_config_value("bot", "author_qq", "0"):
            yield event.plain_result("只有作者才能调整美图配置哦！")
            event.stop_event()
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("这个指令只能在群聊中使用。")
            event.stop_event()
            return
        response = await asyncio.to_thread(
            handle_lolicon_admin_command,
            int(event.get_group_id()),
            event.get_message_str().strip(),
        )
        yield event.plain_result(response)
        event.stop_event()

    @filter.regex(LOLICON_PATTERN, desc="Lolicon 美图命令，支持美图、色图、混合等关键词，并使用迁移后的元数据和群配置。")
    async def lolicon_image(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="lolicon_image"):
            return
        try:
            results = await asyncio.to_thread(
                build_lolicon_results,
                event.get_message_str().strip(),
                event.is_private_chat(),
                int(event.get_group_id() or 0),
            )
        except Exception as exc:
            yield event.plain_result(f"Lolicon 美图获取失败：{exc}")
            event.stop_event()
            return
        if not results:
            return
        for result in results:
            chain = [Plain(result.prefix)]
            if result.image_path:
                chain.append(random_summary_image_from_file(result.image_path))
            elif result.image_url:
                chain.append(random_summary_image_from_url(result.image_url))
            elif result.image_text:
                chain.append(Plain(result.image_text))
            chain.append(Plain(result.suffix))
            yield event.chain_result(chain)
        event.stop_event()

    async def _cache_group_nickname(self, event: AstrMessageEvent) -> None:
        if str(event.get_extra(GROUP_NICKNAME_CACHED_EXTRA, "") or ""):
            return
        group_id = str(event.get_group_id() or "").strip()
        user_id = str(event.get_sender_id() or "").strip()
        if not group_id or not user_id:
            return
        card, nickname = extract_event_sender_nickname_fields(event)
        event.set_extra(GROUP_NICKNAME_CACHED_EXTRA, "1")
        if not card and not nickname:
            return
        store = GroupNicknameStore(get_qqbot_runtime_root())
        try:
            await asyncio.to_thread(
                store.record_group_sender,
                group_id,
                user_id,
                card=card,
                nickname=nickname,
                updated_at=read_event_time_seconds(event),
            )
        except Exception as exc:
            logger.warning(
                "[QQBotFeatures] group nickname cache write failed: group_id=%s user_id=%s error=%s",
                group_id,
                user_id,
                exc,
            )

    @filter.event_message_type(
        EventMessageType.GROUP_MESSAGE,
        priority=3000,
        desc="缓存每条群消息的群名片和 QQ 昵称，供统一用户显示名解析使用。",
    )
    async def cache_group_nickname(self, event: AstrMessageEvent):
        await self._cache_group_nickname(event)

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, desc="记录 RightCodes 生图积分的普通群消息事件。")
    async def record_rightcodes_group_message_points(self, event: AstrMessageEvent):
        if not allow_passive_events(self._feature_mode):
            return
        if str(event.get_sender_id() or "") == str(event.get_self_id() or ""):
            return
        if is_known_bot_sender(event):
            return
        if not str(event.get_message_str() or "").strip():
            return
        store = RightCodesDrawQuotaStore(
            self._rightcodes_config.data_root,
            multiplier=self._rightcodes_config.point_multiplier,
        )
        await asyncio.to_thread(store.record_group_message, event.get_sender_id())

    @filter.on_llm_request(desc="在 LLM 请求前按关键词注入 RightCodes 生图接口知识库。")
    async def inject_rightcodes_draw_catalog(self, event: AstrMessageEvent, req: ProviderRequest):
        request_context = build_current_request_context(event, req.prompt or "")
        query = request_context.combined_query or request_context.current_text
        if not should_inject_rightcodes_draw_catalog(query):
            return
        req.extra_user_content_parts.append(
            TextPart(text=format_rightcodes_draw_catalog_injection(query)).mark_as_temp()
        )
        logger.info(
            "[QQBotFeatures] injected RightCodes draw catalog: session=%s",
            getattr(event, "unified_msg_origin", ""),
        )

    @filter.on_llm_request(desc="在 LLM 请求前把被引用消息作为当前请求原文补入上下文。")
    async def inject_quoted_request_source(self, event: AstrMessageEvent, req: ProviderRequest):
        request_context = build_current_request_context(event, req.prompt or "")
        cached_source_tree = event.get_extra(FORWARD_SOURCE_TREE_EXTRA)
        source_tree = (
            cached_source_tree
            if isinstance(cached_source_tree, tuple)
            else await extract_onebot_source_tree(event)
        )
        source_text = format_source_messages(source_tree)
        if not source_text:
            return
        current_text = request_context.current_text
        request_text = (
            "用户当前请求包含引用/接力语境。下面是本轮请求的来源消息。每条“发送者 QQ”都来自 OneBot 原始消息，"
            "必须区分不同发送者，并把消息内容作为当前请求的上下文事实，不要只按当前短句理解：\n"
            f"{source_text}"
        )
        if current_text:
            request_text += f"\n当前消息：{current_text}"
        req.extra_user_content_parts.append(TextPart(text=request_text).mark_as_temp())
        logger.info(
            "[QQBotFeatures] injected quoted request source: session=%s replies=%s chars=%s",
            getattr(event, "unified_msg_origin", ""),
            len(source_tree),
            len(source_text),
        )

    @filter.event_message_type(EventMessageType.ALL, priority=1500, desc="在普通聊天激活前记录本轮是否明确唤醒。")
    async def capture_draw_intent_wake(self, event: AstrMessageEvent):
        """Snapshot explicit wake state before group activity can promote candidates.

        Args:
            event: Current event; this flag never persists beyond its processing.
        """
        event.set_extra("qqbot_draw_intent_wake", _is_direct_or_private(event))

    @filter.event_message_type(EventMessageType.ALL, desc="RightCodes 生图总入口，处理明确指令和自然语言生图。")
    async def rightcodes_draw_command(self, event: AstrMessageEvent):
        text = extract_plain_text(event).strip()
        if not text:
            return
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="rightcodes_draw"):
            return
        natural_intent = None
        intent_parts = None

        async def call_image_action(action: str, **params: object) -> object:
            """Read source facts through the current platform's public OneBot API."""
            bot = getattr(event, "bot", None)
            if bot is None:
                raise ValueError("当前平台无法读取QQ引用图片")
            return await bot.call_action(action, **params)

        if not looks_like_rightcodes_draw_feature_request(text):
            if not event.get_extra("qqbot_draw_intent_wake", False):
                return
            parts = _raw_event_dict(event).get("message")
            if not isinstance(parts, list):
                parts = [segment.toDict() for segment in event.get_messages()]

            async def classify_intent(prompt: str) -> str:
                """Classify with the selected provider without persisting chat history."""
                provider = self.context.get_using_provider(event.unified_msg_origin)
                if provider is None:
                    raise ValueError("no draw intent provider")
                logger.info("[QQBotFeatures] draw intent provider=%s model=%s", provider.meta().id, provider.get_model())
                response = await provider.text_chat(
                    prompt=prompt, system_prompt=DRAW_INTENT_SYSTEM, contexts=[],
                    session_id=f"draw_intent:{event.unified_msg_origin}", persist=False,
                )
                return response.completion_text

            try:
                natural_intent = await self._draw_intent_router.resolve(
                    parts, sender_id=str(event.get_sender_id()), self_id=str(event.get_self_id()),
                    call_action=call_image_action, classify=classify_intent,
                )
            except Exception as exc:
                logger.warning("[QQBotFeatures] draw intent unavailable: error_type=%s", type(exc).__name__)
                return
            if natural_intent is None or natural_intent.action == "none":
                return
            if natural_intent.action == "clarify":
                yield event.plain_result(f"{natural_intent.clarification} 本次没有扣积分。")
                event.stop_event()
                return
            intent_parts = natural_intent.command_parts()
            text = component_text(intent_parts)
        await self._cache_group_nickname(event)
        store = RightCodesDrawQuotaStore(
            self._rightcodes_config.data_root,
            multiplier=self._rightcodes_config.point_multiplier,
        )
        user_id = str(event.get_sender_id() or "")

        explicit = STANDARD_DRAW_PREFIX.match(text) is not None
        if not explicit and looks_like_rightcodes_draw_points_mutation_request(text):
            yield event.plain_result(format_rightcodes_draw_points_mutation_denied())
            event.stop_event()
            return
        if looks_like_rightcodes_draw_points_query(text):
            balance = await asyncio.to_thread(store.get_balance, user_id)
            yield event.plain_result(format_rightcodes_draw_points_status(balance))
            event.stop_event()
            return
        if looks_like_rightcodes_draw_points_ranking(text):
            ranking = await asyncio.to_thread(store.get_points_ranking, limit=10)
            group_id = event.get_group_id()
            yield event.plain_result(
                format_rightcodes_draw_points_ranking(
                    ranking,
                    resolve_display_name=lambda candidate: resolve_display_name(group_id, candidate),
                )
            )
            event.stop_event()
            return
        if looks_like_rightcodes_draw_help_command(text):
            balance = await asyncio.to_thread(store.get_balance, user_id)
            yield event.plain_result(
                format_rightcodes_draw_model_help(balance.model, multiplier=balance.multiplier)
            )
            event.stop_event()
            return
        if looks_like_rightcodes_draw_model_switch(text):
            model = parse_rightcodes_draw_model_switch(text)
            if model is None:
                candidate = extract_rightcodes_draw_model_switch(text) or ""
                yield event.plain_result(format_rightcodes_draw_model_switch_invalid(candidate))
            else:
                balance = await asyncio.to_thread(store.set_model, user_id, model)
                yield event.plain_result(format_rightcodes_draw_model_switch_success(balance))
            event.stop_event()
            return

        temporary_model = extract_removed_rightcodes_draw_temporary_model(text)
        if temporary_model is not None:
            yield event.plain_result(format_rightcodes_draw_temporary_model_removed(temporary_model))
            event.stop_event()
            return
        draw_request = parse_rightcodes_draw_command(text)
        if draw_request is None:
            if looks_like_rightcodes_draw_invocation(text):
                yield event.plain_result(format_rightcodes_draw_missing_prompt_message())
                event.stop_event()
                return
            return
        balance = await asyncio.to_thread(store.get_balance, user_id)
        draw_request = RightCodesDrawRequest(
            prompt=draw_request.prompt,
            model=balance.model,
            image_urls=draw_request.image_urls,
        )
        try:
            segments = intent_parts if intent_parts is not None else _raw_event_dict(event).get("message")
            if not isinstance(segments, list):
                segments = [segment.toDict() for segment in event.get_messages()]
            preset_parts = await doudouyan_command_parts(segments, call_action=call_image_action)
            if explicit or preset_parts is not None:
                draw_request = await prepare_explicit_draw_request(
                    preset_parts if preset_parts is not None else segments,
                    sender_id=user_id, model=balance.model, call_action=call_image_action,
                )
            else:
                request_context = build_current_request_context(event, text)
                reference_image_urls = extract_image_sources(event)
                if should_rewrite_rightcodes_draw_prompt(
                    draw_request,
                    reply_texts=request_context.reply_texts,
                    image_urls=reference_image_urls,
                ):
                    rewritten_request = await self._rewrite_rightcodes_draw_request(
                        event,
                        draw_request,
                        current_text=request_context.current_text,
                        reply_texts=request_context.reply_texts,
                        reference_image_urls=reference_image_urls,
                        unresolved_media_context=request_context.unresolved_media_context,
                    )
                    if rewritten_request is None:
                        if request_context.unresolved_media_context and not reference_image_urls:
                            yield event.plain_result(format_rightcodes_draw_rewrite_missing_context())
                        else:
                            yield event.plain_result(format_rightcodes_draw_rewrite_failure())
                        event.stop_event()
                        return
                    draw_request = rewritten_request
                draw_request = await preload_draw_references(draw_request)
        except Exception as exc:
            logger.warning("[QQBotFeatures] draw input preparation failed: error_type=%s", type(exc).__name__)
            detail = str(exc) if isinstance(exc, ValueError) else "原图读取失败或超时，请重新附图或引用"
            yield event.plain_result(f"{detail}。本次没有扣积分。")
            event.stop_event()
            return
        quota = await asyncio.to_thread(store.reserve, user_id, model=draw_request.model)
        if not quota.allowed:
            yield event.plain_result(format_draw_quota_exceeded_message(quota))
            event.stop_event()
            return

        timeout_seconds = self._rightcodes_config.draw_timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        refunded = False
        generated = False

        async def refund_once() -> None:
            nonlocal refunded
            if refunded:
                return
            refunded = True
            await asyncio.shield(asyncio.to_thread(store.refund, quota))

        try:
            async with asyncio.timeout_at(deadline):
                start_message = format_draw_start_message(quota)
                start_message += ("\n提示词来源：豆豆眼预设（完整固定原文）" if preset_parts is not None
                                  else "\n提示词来源：用户话语（无预设）")
                if preset_parts is not None:
                    start_message += "\n本次按固定原文生成，不追加其他描述。"
                    if natural_intent is not None and natural_intent.source is not None:
                        start_message += f"\n本次来源：{natural_intent.source.label}"
                    elif component_text(preset_parts).startswith("头像生图"):
                        start_message += "\n本次来源：头像生图指定的头像"
                    else:
                        target = "当前附图" if any(part.get("type") == "image" for part in preset_parts) else "引用图片"
                        start_message += f"\n本次来源：{target}"
                elif natural_intent is not None:
                    start_message += natural_intent.start_detail()
                await event.send(event.plain_result(start_message))
            api_key = self._rightcodes_config.api_key
            if not api_key:
                await refund_once()
                yield event.plain_result("CPA 生图 API Key 还没配置。")
                event.stop_event()
                return

            try:
                async with asyncio.timeout_at(deadline):
                    async with self._rightcodes_draw_lock:
                        remaining = deadline - asyncio.get_running_loop().time()
                        result = await RightCodesDrawClient(
                            api_key=api_key,
                            base_url=self._rightcodes_config.base_url,
                            timeout_seconds=remaining,
                        ).draw(draw_request)
                        generated = True
            except asyncio.TimeoutError:
                await refund_once()
                yield _chain_result_with_reply(
                    event,
                    [Plain(format_rightcodes_draw_timeout(timeout_seconds))],
                )
                event.stop_event()
                return
            except Exception as exc:
                await refund_once()
                yield _chain_result_with_reply(event, [Plain(format_rightcodes_draw_failure(exc))])
                event.stop_event()
                return
        except asyncio.CancelledError:
            if not generated:
                await refund_once()
            raise
        except Exception:
            await refund_once()
            raise

        try:
            await self._deliver_draw_result(event, result, draw_request.model, refund_once)
        finally:
            event.stop_event()

    async def _deliver_draw_result(
        self,
        event: AstrMessageEvent,
        result: RightCodesDrawResult,
        model: str,
        refund: Callable[[], Awaitable[None]],
    ) -> None:
        """Save a generated PNG and await delivery so failures remain observable.

        Args:
            event: Command event with its original reply destination.
            result: Validated image bytes and generation timing.
            model: Selected model for the completion message.
            refund: Request-scoped, at-most-once point refund operation.
        """
        saved = None
        try:
            saved = await asyncio.to_thread(save_generated_image, result.image_bytes, self._rightcodes_config.data_root)
        except Exception as exc:
            logger.error("[QQBotFeatures] draw persistence failed: error_type=%s", type(exc).__name__)
        message = format_rightcodes_draw_success(result, model=model)
        if saved is not None:
            image = random_summary_image_from_file(saved)
        else:
            message += "\n图片未保存到本地，已尝试直接交付，请及时保存。"
            image = Image.fromBytes(result.image_bytes)
            image.__dict__["summary"] = choose_image_summary()
        try:
            async with asyncio.timeout(60):
                await event.send(_chain_result_with_reply(event, [Plain(message), image]))
            return
        except Exception as exc:
            logger.warning("[QQBotFeatures] draw delivery failed: error_type=%s saved=%s", type(exc).__name__, saved)
        if saved is None:
            try:
                await refund()
                notice = "图片已生成，但保存和发送均失败，本次积分已退回。"
            except Exception as exc:
                logger.error("[QQBotFeatures] draw refund failed: error_type=%s", type(exc).__name__)
                notice = "图片已生成，但保存和发送均失败；积分退款失败，请联系管理员处理。"
        else:
            notice = f"图片已生成并保存，但发送失败。请联系管理员取回：{saved.name}。本次未退积分。"
        try:
            async with asyncio.timeout(15):
                await event.send(event.plain_result(notice))
        except Exception as exc:
            logger.warning("[QQBotFeatures] draw failure notice failed: error_type=%s", type(exc).__name__)

    async def _rewrite_rightcodes_draw_request(
        self,
        event: AstrMessageEvent,
        draw_request: RightCodesDrawRequest,
        *,
        current_text: str,
        reply_texts: tuple[str, ...],
        reference_image_urls: tuple[str, ...],
        unresolved_media_context: bool,
    ) -> RightCodesDrawRequest | None:
        if unresolved_media_context and not reference_image_urls:
            logger.info(
                "[QQBotFeatures] skip draw prompt rewrite because media context is unresolved: session=%s",
                getattr(event, "unified_msg_origin", ""),
            )
            return None
        try:
            provider = self.context.get_using_provider(event.unified_msg_origin)
        except Exception as exc:
            logger.warning("[QQBotFeatures] failed to get draw rewrite provider: %s", exc)
            return None
        if provider is None:
            logger.info("[QQBotFeatures] no provider for draw prompt rewrite")
            return None
        rewrite_prompt = build_rightcodes_draw_rewrite_prompt(
            RightCodesDrawRewriteInput(
                prompt=draw_request.prompt,
                model=draw_request.model,
                current_text=current_text,
                reply_texts=reply_texts,
                image_urls=reference_image_urls,
                unresolved_media_context=unresolved_media_context,
            )
        )
        try:
            response = await provider.text_chat(
                prompt=rewrite_prompt,
                session_id=f"rightcodes_draw_rewrite:{event.unified_msg_origin}",
                image_urls=list(reference_image_urls),
                contexts=[],
                system_prompt=RIGHTCODES_DRAW_REWRITE_SYSTEM_PROMPT,
                persist=False,
            )
        except Exception as exc:
            logger.warning("[QQBotFeatures] draw prompt rewrite provider failed: %s", exc)
            return None
        rewrite_result = parse_rightcodes_draw_rewrite_response(
            getattr(response, "completion_text", ""),
            fallback_image_urls=reference_image_urls,
        )
        if rewrite_result is None:
            logger.info(
                "[QQBotFeatures] draw prompt rewrite returned no usable prompt: session=%s",
                getattr(event, "unified_msg_origin", ""),
            )
            return None
        logger.info(
            "[QQBotFeatures] draw prompt rewritten before RightCodes call: session=%s images=%s prompt_chars=%s",
            getattr(event, "unified_msg_origin", ""),
            len(rewrite_result.image_urls),
            len(rewrite_result.prompt),
        )
        return merge_rewritten_draw_request(draw_request, rewrite_result)

    @filter.regex(ARC_RECOMMEND_PATTERN, desc="Arcaea PTT 推荐命令，例如 arctj10.5，按本地曲库和定数缓存推荐谱面。")
    async def arc_recommend(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_recommend"):
            return
        try:
            result = await asyncio.to_thread(
                build_arc_recommendation,
                event.get_message_str().strip(),
            )
        except Exception as exc:
            yield event.plain_result(f"Arc 推荐失败：{exc}")
            event.stop_event()
            return
        if result.image_path is not None:
            yield event.chain_result(
                [random_summary_image_from_file(result.image_path), Plain(f"\n{result.text}")]
            )
        else:
            yield event.plain_result(result.text)
        event.stop_event()

    @filter.regex(ARC_ACTIVITY_PATTERN, desc="Arcaea 活动梯子查询命令，支持 archd 和 arctz。")
    async def arc_activity(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_activity"):
            return
        try:
            messages = await asyncio.to_thread(build_arc_activity_messages)
        except Exception as exc:
            yield event.plain_result(f"Arc 活动梯子查询失败：{exc}")
            event.stop_event()
            return
        for message in messages or ["当前没有活动梯子。"]:
            yield event.plain_result(message)
        event.stop_event()

    @filter.regex(ARC_APK_UPDATE_PATTERN, desc="作者限定的 Arcaea 安装包更新命令，支持 xz 和 arcxz。")
    async def arc_apk_update(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_apk_update"):
            return
        if str(event.get_sender_id()) != get_qqbot_config_value("bot", "author_qq", "0"):
            yield event.plain_result("只有作者可以使用这个指令。")
            event.stop_event()
            return
        try:
            manager = get_arc_apk_update_manager(self)
            message = await manager.query_and_update()
        except Exception as exc:
            yield event.plain_result(f"Arc 安装包下载查询失败：{exc}")
            event.stop_event()
            return
        yield event.plain_result(message)
        event.stop_event()

    @filter.regex(ARC_GUESS_START_PATTERN, desc="开始 Arcaea 字母猜歌局，支持 zm 或 arczm 加题目数量。")
    async def arc_guess_start(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_guess_song"):
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("Arc 猜歌只能在群聊中开始。")
            event.stop_event()
            return
        try:
            result = await asyncio.to_thread(
                start_arc_guess_game,
                int(event.get_group_id()),
                event.get_message_str().strip(),
            )
        except Exception as exc:
            yield event.plain_result(f"Arc 猜歌开始失败：{exc}")
            event.stop_event()
            return
        yield event.plain_result(str(result))
        event.stop_event()

    @filter.regex(ARC_GUESS_ART_START_PATTERN, desc="开始或继续 Arcaea 曲绘猜歌局，支持 qh 或 arcqh 加网格大小。")
    async def arc_guess_art_start(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_guess_art"):
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("Arc 猜歌只能在群聊中开始。")
            event.stop_event()
            return
        try:
            result = await asyncio.to_thread(
                start_or_open_arc_art_guess,
                int(event.get_group_id()),
                event.get_message_str().strip(),
            )
        except Exception as exc:
            yield event.plain_result(f"Arc 曲绘猜歌失败：{exc}")
            event.stop_event()
            return
        yield build_arc_guess_event_result(event, result)
        event.stop_event()

    @filter.regex(ARC_GUESS_ART_TILE_PATTERN, desc="Arcaea 曲绘猜歌补图命令，打开下一块曲绘区域。")
    async def arc_guess_art_tile(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_guess_art_tile"):
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("Arc 猜歌只能在群聊中进行。")
            event.stop_event()
            return
        try:
            result = await asyncio.to_thread(
                open_arc_art_guess_tile,
                int(event.get_group_id()),
            )
        except Exception as exc:
            yield event.plain_result(f"Arc 曲绘补图失败：{exc}")
            event.stop_event()
            return
        yield build_arc_guess_event_result(event, result)
        event.stop_event()

    @filter.regex(ARC_GUESS_REVEAL_PATTERN, desc="Arcaea 猜歌揭晓命令，结束当前字母或曲绘猜歌局并公布答案。")
    async def arc_guess_reveal(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="arc_guess_art_reveal"):
            return
        if event.is_private_chat() or not event.get_group_id():
            yield event.plain_result("Arc 猜歌只能在群聊中进行。")
            event.stop_event()
            return
        try:
            result = await asyncio.to_thread(reveal_arc_guess, int(event.get_group_id()))
        except Exception as exc:
            yield event.plain_result(f"Arc 猜歌揭晓失败：{exc}")
            event.stop_event()
            return
        yield build_arc_guess_event_result(event, result)
        event.stop_event()

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, desc="Arcaea 猜歌局答案监听器，只在已有猜歌会话中处理开字母、猜答案和曲绘答案。")
    async def arc_guess_session_answer(self, event: AstrMessageEvent):
        if not (allow_passive_events(self._feature_mode) or _is_direct_or_private(event)):
            return
        if event.get_sender_id() == event.get_self_id() or is_known_bot_sender(event):
            return
        text = event.get_message_str().strip()
        if not text or not event.get_group_id():
            return
        await self._cache_group_nickname(event)
        try:
            result = await asyncio.to_thread(
                handle_arc_guess_session_text,
                int(event.get_group_id()),
                text,
                get_player_name(event),
            )
        except Exception as exc:
            logger.warning("[QQBotFeatures] Arc guess session handling failed: %s", exc)
            return
        if result is None:
            return
        yield build_arc_guess_event_result(event, result)
        event.stop_event()

    @filter.regex(KUN_PATTERN, desc="养鲲玩法命令入口，处理摸鲲、属性、背包、商城、签到、排行、挑战、赠送等存档操作。")
    async def kun_command(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="kun_game"):
            return
        await self._cache_group_nickname(event)
        response = await asyncio.to_thread(handle_kun_command, event)
        if response is None:
            return
        yield event.plain_result(response)
        event.stop_event()

    @filter.regex(SAKURA_PATTERN, desc="落樱之都基础玩法入口，处理注册、改名、个人信息、经验、樱币、加点和恢复。")
    async def sakura_command(self, event: AstrMessageEvent):
        if not _should_handle_migrated_command(event, self._feature_mode, command_type="sakura_game"):
            return
        response = await asyncio.to_thread(handle_sakura_command, event)
        if response is None:
            return
        yield event.plain_result(response)
        event.stop_event()

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, desc="群聊随机复读监听器，连续相同纯文本达到条件后按概率复读并进入冷却。")
    async def reread(self, event: AstrMessageEvent):
        if not allow_passive_events(self._feature_mode):
            return
        text = event.get_message_str().strip()
        if should_skip_reread(event, text):
            return
        message_id = str(getattr(event.message_obj, "message_id", "") or "")
        sender_id = str(event.get_sender_id() or "")
        if not self._reread_state.observe(
            event.get_group_id(),
            text,
            message_id=message_id,
            sender_id=sender_id,
        ):
            return
        yield event.plain_result(text)

    @filter.platform_adapter_type("aiocqhttp")
    @filter.event_message_type(EventMessageType.ALL, desc="OneBot 社交事件监听器，处理好友申请、邀请入群、自身入群私聊通知和新成员欢迎。")
    async def onebot_social_events(self, event: AstrMessageEvent):
        raw = _raw_event_dict(event)
        if not raw:
            return
        post_type = str(raw.get("post_type") or "")
        if post_type == "notice":
            if not allow_passive_events(self._feature_mode):
                return
            async for result in self._handle_onebot_notice(event, raw):
                yield result
            return
        if post_type == "request":
            await self._handle_onebot_request(event, raw)

    async def _handle_onebot_notice(self, event: AstrMessageEvent, raw: dict):
        notice_type = str(raw.get("notice_type") or "")
        if notice_type == "group_increase":
            user_id = str(raw.get("user_id") or "")
            self_id = str(raw.get("self_id") or event.get_self_id())
            if not event.get_group_id() or not user_id:
                return
            if user_id == self_id:
                await self._notify_self_joined_group(event, str(event.get_group_id()))
            elif should_send_member_welcome(
                user_id=user_id,
                self_id=self_id,
                known_bot_ids=KNOWN_SISTER_BOT_QQ_IDS,
            ):
                yield event.chain_result(
                    [
                        _at(user_id),
                        Plain(
                            format_group_member_welcome(
                                self_id,
                                random.choice(GROUP_MEMBER_WELCOME_EXPRESSIONS),
                            )
                        ),
                    ]
                )
            return
    async def _handle_onebot_request(self, event: AstrMessageEvent, raw: dict) -> None:
        request_type = str(raw.get("request_type") or "")
        sub_type = str(raw.get("sub_type") or "")
        user_id = str(raw.get("user_id") or "")
        group_id = str(raw.get("group_id") or "")
        flag = str(raw.get("flag") or "")
        if request_type == "friend":
            if not self._auto_approve_friend_requests:
                logger.info("[QQBotFeatures] friend request observed: user_id=%s", user_id)
                return
            await self._approve_onebot_request(
                event,
                action="set_friend_add_request",
                payload={"flag": flag, "approve": True},
                log_label="friend request",
                group_id=group_id,
                user_id=user_id,
                sub_type=sub_type,
                flag=flag,
            )
            return
        if request_type == "group" and sub_type == "invite":
            if not self._auto_approve_group_invites:
                logger.info(
                    "[QQBotFeatures] group invite request observed: group_id=%s user_id=%s",
                    group_id,
                    user_id,
                )
                return
            approved = await self._approve_onebot_request(
                event,
                action="set_group_add_request",
                payload={"flag": flag, "sub_type": sub_type, "approve": True},
                log_label="group invite request",
                group_id=group_id,
                user_id=user_id,
                sub_type=sub_type,
                flag=flag,
            )
            if approved and group_id and user_id:
                self._group_inviter_by_group_id[group_id] = user_id

    async def _approve_onebot_request(
        self,
        event: AstrMessageEvent,
        *,
        action: str,
        payload: dict[str, object],
        log_label: str,
        group_id: str,
        user_id: str,
        sub_type: str,
        flag: str,
    ) -> bool:
        if not flag:
            logger.warning(
                "[QQBotFeatures] cannot approve %s without flag: group_id=%s user_id=%s sub_type=%s",
                log_label,
                group_id,
                user_id,
                sub_type,
            )
            return False
        try:
            api = AstrBotOneBotApi(event)
            await api.call_api(action, **payload)
        except Exception as exc:
            logger.exception(
                "[QQBotFeatures] failed to approve %s: action=%s group_id=%s user_id=%s sub_type=%s flag=%s error=%s",
                log_label,
                action,
                group_id,
                user_id,
                sub_type,
                flag,
                exc,
            )
            return False
        logger.info(
            "[QQBotFeatures] approved %s: action=%s group_id=%s user_id=%s sub_type=%s flag=%s",
            log_label,
            action,
            group_id,
            user_id,
            sub_type,
            flag,
        )
        return True

    async def _notify_self_joined_group(self, event: AstrMessageEvent, group_id: str) -> None:
        inviter_id = self._group_inviter_by_group_id.pop(group_id, "")
        target_user_id = inviter_id or OWNER_QQ
        group_name = await self._get_group_name(event, group_id)
        message = format_self_join_private_notice(group_name, group_id)
        try:
            await AstrBotOneBotApi(event).call_api(
                "send_private_msg",
                user_id=int(target_user_id),
                message=message,
            )
        except Exception as exc:
            logger.exception(
                "[QQBotFeatures] failed to notify self group join: group_id=%s target_user_id=%s error=%s",
                group_id,
                target_user_id,
                exc,
            )
            return
        logger.info(
            "[QQBotFeatures] notified self group join privately: group_id=%s target_user_id=%s inviter_id=%s",
            group_id,
            target_user_id,
            inviter_id,
        )

    async def _get_group_name(self, event: AstrMessageEvent, group_id: str) -> str:
        try:
            result = await AstrBotOneBotApi(event).call_api(
                "get_group_info",
                group_id=int(group_id),
                no_cache=True,
            )
        except Exception as exc:
            logger.warning(
                "[QQBotFeatures] failed to read group info for self join notice: group_id=%s error=%s",
                group_id,
                exc,
            )
            return ""
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else result
            return str(data.get("group_name") or "").strip()
        return ""


def _is_direct_or_private(event: AstrMessageEvent) -> bool:
    return event.is_private_chat() or bool(getattr(event, "is_at_or_wake_command", False))


def extract_plain_text(event: AstrMessageEvent) -> str:
    return extract_event_plain_text(event)


def _should_handle_migrated_command(
    event: AstrMessageEvent,
    feature_mode: str,
    *,
    command_type: str = "generic",
) -> bool:
    del feature_mode, command_type
    return not is_known_bot_sender(event)


def looks_like_qqbot_fixed_command(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if parse_rightcodes_draw_command(normalized) is not None:
        return True
    if looks_like_rightcodes_draw_feature_request(normalized):
        return True
    if looks_like_sub2api_usage_command(normalized):
        return True
    if looks_like_meme_manager_command(normalized):
        return True
    return any(pattern.search(normalized) for pattern in FIXED_COMMAND_PATTERNS)


def is_known_bot_sender(event: AstrMessageEvent) -> bool:
    return is_known_bot_sender_id(event.get_sender_id())


def _comic_download_estimate_minutes(
    queue_position: int,
    max_concurrent_jobs: int,
) -> tuple[int, int]:
    """Return a rough completion range from the FIFO position and concurrency."""
    concurrency = max(1, int(max_concurrent_jobs))
    position = max(0, int(queue_position))
    batches = 1 + ((position + concurrency - 1) // concurrency if position else 0)
    return 5 * batches, 15 * batches


def _chain_result_with_reply(event: AstrMessageEvent, chain: list[object]):
    reply = _reply_to_event_message(event)
    if reply is not None:
        return event.chain_result([reply, *chain])
    return event.chain_result(chain)


def _reply_to_event_message(event: AstrMessageEvent) -> Reply | None:
    message_id = getattr(getattr(event, "message_obj", None), "message_id", None)
    if message_id in (None, ""):
        return None
    return Reply(id=message_id)


def _raw_event_dict(event: AstrMessageEvent) -> dict:
    raw = getattr(event.message_obj, "raw_message", None)
    if isinstance(raw, dict):
        return raw
    try:
        return dict(raw)
    except Exception:
        return {}


def extract_event_sender_nickname_fields(event: AstrMessageEvent) -> tuple[str, str]:
    raw_sender = _raw_event_dict(event).get("sender")
    if isinstance(raw_sender, dict):
        card = str(raw_sender.get("card") or "").strip()
        nickname = str(raw_sender.get("nickname") or "").strip()
        if card or nickname:
            return card, nickname
    return "", str(event.get_sender_name() or "").strip()


def _at(user_id: str):
    return At(qq=user_id)


def find_feature(key: str) -> FeatureSpec | None:
    normalized = key.strip().lower()
    if not normalized:
        return None
    for feature in FEATURES:
        names = (feature.name, *feature.aliases)
        normalized_names = [name.lower() for name in names]
        if normalized in normalized_names:
            return feature
        if any(normalized in name or name in normalized for name in normalized_names):
            return feature
    return None


def build_menu_text(feature_mode: str = FEATURE_MODE_FULL) -> str:
    lines = ["AstrBot 功能清单：", build_feature_mode_text(feature_mode)]
    for section in MENU_SECTIONS:
        lines.append(f"- {section.name}：{section.status}")
    lines.append("发送 菜单模块名 查看具体命令，例如 菜单棉花糖互动 / 菜单Arcaea。")
    return "\n".join(lines)


def build_feature_menu_text(feature) -> str:
    lines = [f"{feature.name}：{feature.status}"]
    lines.extend(feature.lines)
    return "\n".join(lines)


def read_feature_mode(config=None) -> str:
    del config
    return FEATURE_MODE_FULL


def read_bool_config(config, key: str, *, default: bool) -> bool:
    if config is None:
        return default
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "启用", "开启"}:
            return True
        if normalized in {"0", "false", "no", "off", "禁用", "关闭"}:
            return False
    logger.warning(
        "[QQBotFeatures] invalid boolean config %s=%r, fallback to %s",
        key,
        value,
        default,
    )
    return default


class ScopedPluginConfig:
    def __init__(self, base_config, *, prefix: str) -> None:
        self._base_config = base_config
        self._prefix = prefix

    def get(self, key: str, default=None):
        prefixed_key = f"{self._prefix}_{key}"
        value = get_config_value(self._base_config, prefixed_key, None)
        if value is not None:
            return value
        value = get_config_value(self._base_config, key, None)
        if value is not None:
            return value
        return default


def resolve_astrbot_data_root() -> Path:
    astrbot_root = Path(os.environ.get("ASTRBOT_ROOT") or Path(__file__).resolve().parents[3])
    return astrbot_root.resolve() / "data"


def get_config_value(config, key: str, default=None):
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            try:
                value = getter(key)
            except Exception:
                return default
            return default if value is None else value
        except Exception:
            return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def safe_event_value(event: AstrMessageEvent, method_name: str) -> str:
    method = getattr(event, method_name, None)
    if not callable(method):
        return ""
    try:
        return str(method() or "").strip()
    except Exception:
        return ""


def _should_reply_too_long_to_read_event(event: AstrMessageEvent, *, threshold: int) -> bool:
    if threshold <= 0:
        return False
    if event.is_private_chat():
        return False
    if not _is_direct_or_private(event):
        return False
    if is_known_bot_sender(event):
        return False
    text = extract_event_plain_text(event) or str(event.get_message_str() or "")
    if not should_reply_too_long_to_read(text, threshold=threshold):
        return False
    if looks_like_qqbot_fixed_command(text):
        return False
    return True


def _should_disable_segmented_reply_for_result(
    context: Context,
    result,
    *,
    override_enabled: bool,
) -> bool:
    if result is None or not result.is_model_result():
        return False
    segmented_reply = _read_segmented_reply_config(context)
    if segmented_reply.get("enable") is not True:
        return False
    if segmented_reply.get("only_llm_result", True) is not True:
        return False
    if str(segmented_reply.get("split_mode", "regex")) != "regex":
        return False
    return should_disable_model_regex_segmenting(
        segmented_reply,
        is_model_result=True,
        override_enabled=override_enabled,
    )


def _read_segmented_reply_config(context: Context) -> dict:
    get_config = getattr(context, "get_config", None)
    config = None
    if callable(get_config):
        try:
            config = get_config()
        except Exception:
            config = None
    if not isinstance(config, dict):
        return {}
    platform_settings = config.get("platform_settings")
    if not isinstance(platform_settings, dict):
        return {}
    segmented_reply = platform_settings.get("segmented_reply")
    return segmented_reply if isinstance(segmented_reply, dict) else {}


def _plain_result_text(chain) -> str:
    if not chain:
        return ""
    texts: list[str] = []
    for comp in chain:
        if not isinstance(comp, CorePlain):
            return ""
        texts.append(comp.text)
    return "".join(texts).strip()


def _plain_message_chain_text(message_chain) -> str:
    parts: list[str] = []
    for segment in getattr(message_chain, "chain", []):
        if isinstance(segment, CorePlain):
            parts.append(segment.text)
    return "".join(parts).strip()


def allow_local_runtime_tools(event: AstrMessageEvent) -> bool:
    return event.is_private_chat() and safe_event_value(event, "get_sender_id") == OWNER_QQ


def remove_forbidden_local_tools(event: AstrMessageEvent, req: ProviderRequest) -> list[str]:
    toolset = getattr(req, "func_tool", None)
    if toolset is None or allow_local_runtime_tools(event):
        return []
    tools = list(getattr(toolset, "tools", []) or [])
    removed: list[str] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if not is_dangerous_local_tool_name(name):
            continue
        remover = getattr(toolset, "remove_tool", None)
        if callable(remover):
            remover(name)
        else:
            toolset.tools = [
                candidate
                for candidate in getattr(toolset, "tools", [])
                if getattr(candidate, "name", "") != name
            ]
        removed.append(name)
    if getattr(toolset, "empty", None) and toolset.empty():
        req.func_tool = None
    return removed


def read_bot_display_name(event: AstrMessageEvent) -> str:
    del event
    return "云栖"


def allow_passive_events(feature_mode: str) -> bool:
    return True


def is_bot_admin_or_self(event: AstrMessageEvent) -> bool:
    sender_id = str(event.get_sender_id())
    return sender_id == str(get_author_qq()) or sender_id == str(event.get_self_id())


def is_migrated_plugin_enabled(plugin_id: str) -> bool:
    from .legacy_services.settings_store import SettingsStore

    return SettingsStore(get_qqbot_runtime_root(), get_author_qq()).get_plugin_enabled(plugin_id)


def build_feature_mode_text(feature_mode: str) -> str:
    return "当前模式：full，AstrBot 接管已迁移自动事件。"


def should_skip_reread(event: AstrMessageEvent, text: str) -> bool:
    if not text:
        return True
    if is_known_bot_sender(event):
        return True
    if getattr(event, "is_at_or_wake_command", False):
        return True
    if looks_like_command(text):
        return True
    if _raw_event_dict(event).get("post_type") != "message":
        return True
    messages = event.get_messages()
    return bool(messages) and not all(isinstance(segment, Plain) for segment in messages)


def looks_like_command(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(("/", "!", "！", ".", "。")) or bool(
        re.match(r"^[a-zA-Z]{1,16}\b", stripped)
    )




class AstrBotOneBotApi:
    def __init__(self, event: AstrMessageEvent) -> None:
        self._bot = getattr(event, "bot", None)
        self.self_id = str(event.get_self_id() or "")
        if self._bot is None:
            raise RuntimeError("当前事件没有 aiocqhttp bot 实例")

    async def call_api(self, action: str, **kwargs):
        return await self._bot.call_action(action, **kwargs)


async def run_group_file_cleanup(event: AstrMessageEvent) -> dict[str, object]:
    from .legacy_services.group.file_cleanup_service import (
        ShapezGroupFileCleanupService,
        ShapezGroupFileCleanupStore,
    )

    api = AstrBotOneBotApi(event)
    group_id = int(event.get_group_id())
    service = ShapezGroupFileCleanupService(
        store=ShapezGroupFileCleanupStore(
            get_runtime_db_root() / "shapez_file_cleanup_state.json"
        ),
        group_id=str(group_id),
        timezone_name=get_qqbot_config_value("bot", "timezone", "Asia/Shanghai"),
    )
    result = await service.scan_and_notify_group(api)
    if result.get("violating_user_count") == 0:
        await api.call_api(
            "send_group_msg",
            group_id=group_id,
            message="当前没有超过一周的外层群文件需要清理。",
        )
    elif result.get("failed_group_message_count"):
        await api.call_api(
            "send_group_msg",
            group_id=group_id,
            message="部分文件清理名单没有发出，对应名单已跳过禁言。",
        )
    return result


def build_arc_recommendation(text: str) -> ArcRecommendationResult:
    from .legacy_services.arc.alias_service import load_song_titles
    from .legacy_services.arc.constant_service import ArcConstantService
    from .legacy_services.arc.service import ArcService

    ptt = parse_arc_recommend_ptt(text)
    if ptt is None:
        raise ValueError("用法：arctj10.5")
    assets_root = get_arc_assets_root()
    service = ArcService(assets_root)
    constant_service = ArcConstantService(
        get_runtime_db_root() / "arc" / "constants.json"
    )
    song_titles = load_song_titles(assets_root / "官谱" / "songlist")
    constant_service.sync_missing_constants(song_titles)
    constant_cache = constant_service.load_constant_cache()
    chart = service.recommend_chart_by_ptt(ptt, constant_cache)
    return ArcRecommendationResult(
        text=service.build_recommendation_text(ptt, chart),
        image_path=chart.jacket_path,
    )


def build_arc_activity_messages() -> list[str]:
    from .legacy_services.arc.event_service import ArcEventService

    service = ArcEventService(
        timezone=get_qqbot_config_value("bot", "timezone", "Asia/Shanghai")
    )
    events = service.fetch_active_events()
    return service.render_event_messages(events)


def build_arc_background_service():
    from .legacy_services.arc.alias_service import ArcAliasService, load_song_titles
    from .legacy_services.arc.background_service import ArcBackgroundService
    from .legacy_services.arc.constant_service import ArcConstantService
    from .legacy_services.arc.event_service import ArcEventService, _fetch_latest_arc_version
    from .legacy_services.feature_catalog import get_feature_by_menu_key
    from .legacy_services.settings_store import SettingsStore

    data_root = get_qqbot_runtime_root()
    assets_root = get_arc_assets_root()
    alias_service = ArcAliasService(
        assets_root,
        data_root / "db" / "arc" / "guess_aliases.json",
    )
    constant_service = ArcConstantService(data_root / "db" / "arc" / "constants.json")
    return ArcBackgroundService(
        state_path=data_root / "db" / "arc" / "background_state.json",
        settings_store=SettingsStore(data_root, get_author_qq()),
        arc_feature=get_feature_by_menu_key("arc"),
        author_qq=get_author_qq(),
        version_fetcher=_fetch_latest_arc_version,
        event_service=ArcEventService(
            timezone=get_qqbot_config_value("bot", "timezone", "Asia/Shanghai")
        ),
        alias_service=alias_service,
        guess_service=get_arc_guess_service(),
        constant_service=constant_service,
        constant_song_loader=lambda: load_song_titles(assets_root / "官谱" / "songlist"),
        timezone_name=get_qqbot_config_value("bot", "timezone", "Asia/Shanghai"),
    )


def start_arc_guess_game(room_id: int, text: str):
    count = parse_arc_guess_start_count(text)
    if count is None:
        raise ValueError("用法：arczm5")
    service = get_arc_guess_service()
    return service.start_game(room_id, count)


def start_or_open_arc_art_guess(room_id: int, text: str):
    service = get_arc_guess_service()
    return service.start_or_open_art_tile(room_id, parse_arc_guess_art_grid_size(text))


def open_arc_art_guess_tile(room_id: int):
    service = get_arc_guess_service()
    return service.start_or_open_art_tile(room_id)


def reveal_arc_guess(room_id: int):
    service = get_arc_guess_service()
    return service.reveal_answers(room_id)


def handle_arc_guess_session_text(room_id: int, text: str, player_name: str):
    service = get_arc_guess_service()
    session = service.get_session(room_id)
    if session is None:
        return None
    if session.mode == "letters":
        letter = parse_arc_open_letter(text)
        if letter is not None:
            return service.open_letter(room_id, letter)
        payload = parse_arc_guess_submission(text)
        if payload is None:
            return None
        question_index, answer = payload
        return service.guess(room_id, question_index, answer, player_name)
    if session.mode == "art":
        answer = parse_arc_guess_art_submission(text)
        if answer is None:
            return None
        if not text.strip().startswith("猜") and not service.is_plausible_answer(answer, session.art_aliases or []):
            return None
        return service.guess_art(room_id, answer, player_name)
    return None


def parse_arc_recommend_ptt(text: str) -> float | None:
    match = re.fullmatch(r"arctj\s*([0-9]+(?:\.[0-9]+)?)", text.strip())
    if match is None:
        return None
    return float(match.group(1))


def parse_arc_guess_start_count(text: str) -> int | None:
    match = re.fullmatch(r"(?:arczm|zm)\s*([1-9][0-9]*)?", text.strip())
    if match is None:
        return None
    if not match.group(1):
        return 10
    return int(match.group(1))


def parse_arc_guess_art_grid_size(text: str) -> int | str | None:
    match = re.fullmatch(r"(?:arcqh|qh)\s*([1-9][0-9]*|max)", text.strip(), re.IGNORECASE)
    if match is None:
        return None
    raw_value = match.group(1).lower()
    if raw_value == "max":
        return "max"
    return int(raw_value)


def parse_arc_open_letter(text: str) -> str | None:
    match = re.fullmatch(r"开\s*(\S)", text.strip())
    if match is None:
        return None
    return match.group(1).lower()


def parse_arc_guess_submission(text: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"(?:猜\s*)?([1-9][0-9]*)\s*(.+)", text.strip())
    if match is None:
        return None
    return int(match.group(1)), match.group(2).strip()


def parse_arc_guess_art_submission(text: str) -> str | None:
    stripped = text.strip()
    if re.fullmatch(r"(?:猜\s*)?[1-9][0-9]*\s*.+", stripped):
        return None
    match = re.fullmatch(r"猜\s*(.+)", stripped)
    if match is not None:
        return match.group(1).strip()
    if stripped.startswith("猜") or is_arc_guess_control_command(stripped):
        return None
    return stripped or None


def is_arc_guess_control_command(text: str) -> bool:
    stripped = text.strip()
    return (
        parse_arc_recommend_ptt(stripped) is not None
        or parse_arc_guess_start_count(stripped) is not None
        or re.fullmatch(ARC_GUESS_ART_START_PATTERN, stripped) is not None
        or re.fullmatch(ARC_GUESS_ART_TILE_PATTERN, stripped) is not None
        or parse_arc_open_letter(stripped) is not None
        or re.fullmatch(ARC_GUESS_REVEAL_PATTERN, stripped) is not None
        or re.fullmatch(ARC_ACTIVITY_PATTERN, stripped) is not None
        or re.fullmatch(ARC_APK_UPDATE_PATTERN, stripped) is not None
    )


def get_arc_apk_update_manager(plugin: QQBotFeaturesPlugin):
    from .legacy_services.arc.apk_update_service import ArcApkUpdateManager
    from .legacy_services.arc.arcaea_record_apk_downloader import ArcaeaRecordApkDownloader
    from .legacy_services.arc.event_service import _fetch_latest_arc_version

    if plugin._arc_apk_update_manager is None:
        data_root = get_qqbot_runtime_root()
        plugin._arc_apk_update_manager = ArcApkUpdateManager(
            state_path=data_root / "db" / "arc" / "background_state.json",
            version_fetcher=_fetch_latest_arc_version,
            downloader=ArcaeaRecordApkDownloader(
                project_root=get_required_qqbot_config_path(
                    "paths",
                    "arcaea_record_root",
                ),
                target_dir=get_arc_assets_root(),
                maven_command=get_qqbot_config_value("paths", "arcaea_record_maven", ""),
                java_home=get_qqbot_config_value("paths", "arcaea_record_java_home", ""),
            ),
            timezone_name=get_qqbot_config_value("bot", "timezone", "Asia/Shanghai"),
        )
    return plugin._arc_apk_update_manager


def get_arc_guess_service():
    from .legacy_services.arc.guess_service import ArcGuessService

    return ArcGuessService(
        assets_root=get_arc_assets_root(),
        alias_cache_path=get_runtime_db_root() / "arc" / "guess_aliases.json",
        state_path=get_runtime_db_root() / "arc" / "guess_sessions.json",
        output_root=get_runtime_cache_root() / "arc",
    )


def build_arc_guess_event_result(event: AstrMessageEvent, result):
    image_path = getattr(result, "image_path", None)
    text = getattr(result, "text", str(result))
    if image_path is None:
        return event.plain_result(text)
    return event.chain_result(
        [random_summary_image_from_file(image_path), Plain(f"\n{text}")]
    )


def get_arc_assets_root() -> Path:
    raw = get_qqbot_config_value("paths", "arc_assets_root", "")
    if raw:
        return Path(raw)
    return get_workspace_root() / "data" / "arc"


def get_required_qqbot_config_path(section: str, key: str) -> Path:
    raw = get_qqbot_config_value(section, key, "").strip()
    if not raw:
        raise RuntimeError(f"缺少 AstrBot 迁移配置 {section}.{key}")
    return Path(raw)


def render_shapez_command(command: str, argument: str) -> ShapezRenderResult:
    from .legacy_services.shapez.service import render_shape_chart, render_shape_code, render_shape_path

    output_root = get_runtime_cache_root()
    if command in {"path", "path1", "path2"}:
        tree, output, path_text = render_shape_path(output_root, argument)
        return ShapezRenderResult(
            image_path=output,
            text=f"\n短代码：{tree.shortcode}\n{path_text}",
        )
    if command in {"chart", "chart1", "chart2"}:
        shape, output, shape_text = render_shape_chart(output_root, argument)
        return ShapezRenderResult(
            image_path=output,
            text=f"\n短代码：{shape.short_key}\n{shape_text}",
        )
    shape, output = render_shape_code(output_root, argument)
    return ShapezRenderResult(image_path=output, text=f"\n短代码：{shape.short_key}")


def handle_lolicon_admin_command(group_id: int, text: str) -> str:
    from .legacy_services.settings_store import SettingsStore

    store = SettingsStore(get_qqbot_runtime_root(), get_author_qq())
    group_r18, show_image = store.get_lolicon_config(group_id)
    if text == "开群色图":
        store.set_lolicon_config(group_id, True, show_image)
        return "已开启群色图！"
    if text == "关群色图":
        store.set_lolicon_config(group_id, False, show_image)
        return "已关闭群色图！"
    if text == "开图片显示":
        store.set_lolicon_config(group_id, group_r18, True)
        return "已开启图片显示！\n注意，开启此功能极有可能导致无法接收到消息！\n即使开启，r18图片也不会有缩略图显示~"
    if text == "关图片显示":
        store.set_lolicon_config(group_id, group_r18, False)
        return "已关闭图片显示！"
    return "未知美图配置指令。"


def build_lolicon_results(text: str, is_private: bool, group_id: int = 0) -> list[LoliconRenderResult]:
    from .legacy_services.lolicon.service import (
        LoliconImageStore,
        LoliconMode,
        fetch_lolicon_items,
        parse_lolicon_command,
    )
    from .legacy_services.settings_store import SettingsStore

    command = parse_lolicon_command(text)
    if command is None:
        return []
    show_image = True
    if not is_private:
        group_r18, show_image = SettingsStore(
            get_qqbot_runtime_root(),
            get_author_qq(),
        ).get_lolicon_config(group_id)
        if command.mode != LoliconMode.NON_R18 and not group_r18:
            return [
                LoliconRenderResult(
                    prefix="",
                    suffix="本群当前设置为群内只能查看非R18图片！\n请私聊发送指令QwQ",
                )
            ]
    items = fetch_lolicon_items(command.mode, command.num, command.tags)
    if not items:
        return [
            LoliconRenderResult(
                prefix="",
                suffix="没有找到符合你要求的图片呢QAQ\n尝试减少一些tag吧！",
            )
        ]
    store = LoliconImageStore(get_qqbot_runtime_root())
    results: list[LoliconRenderResult] = []
    for index, item in enumerate(items, start=1):
        prepared = store.prepare_item(item)
        should_send_image = show_image or not prepared.r18
        image_path = prepared.local_path if should_send_image and prepared.local_path is not None else None
        image_url = prepared.url if should_send_image and image_path is None else ""
        image_text = "" if should_send_image else prepared.url
        results.append(
            LoliconRenderResult(
                prefix=f"图片索引：{index} / {len(items)}\n",
                image_path=image_path,
                image_url=image_url,
                image_text=image_text,
                suffix=(
                    f"\n{prepared.title}(PID {prepared.pid})\nby {prepared.author}(UID {prepared.uid})"
                    f"\nTags: {', '.join(prepared.tags) if prepared.tags else '-'}"
                ),
            )
        )
    return results


def get_author_qq() -> int:
    raw = get_qqbot_config_value("bot", "author_qq", OWNER_QQ)
    try:
        return int(raw)
    except ValueError:
        return int(OWNER_QQ)


def handle_kun_command(event: AstrMessageEvent) -> str | None:
    from .legacy_services.kun.service import KunService

    service = KunService(get_runtime_db_root() / "kun" / "users.json")
    at_ids = [int(segment.qq) for segment in event.get_messages() if isinstance(segment, At) and str(segment.qq).isdigit()]
    return service.handle_command(
        event.get_message_str().strip(),
        int(event.get_sender_id()),
        int(read_event_time_seconds(event) * 1000),
        is_group=not event.is_private_chat(),
        at_id=at_ids[0] if at_ids else None,
        is_admin=str(event.get_sender_id()) == OWNER_QQ,
        group_id=int(event.get_group_id() or 0),
        resolve_display_name=resolve_display_name,
    )


def handle_sakura_command(event: AstrMessageEvent) -> str | None:
    from .legacy_services.sakura.service import SakuraService

    text = event.get_message_str().strip()
    user_id = int(event.get_sender_id())
    service = SakuraService(get_runtime_db_root() / "sakura" / "players.json")
    player = service.get_player(user_id)

    if text == "落樱之都":
        return (
            "-===🌸落樱之都🌸===-\n"
            "个人信息◇人物加点\n"
            "我的背包◇我的任务\n"
            "装备强化◇落樱商城\n"
            "单人副本◇魔塔挑战\n"
            "多人副本◇竞技战斗\n"
            "注册xxx / 改名xxx / 个人信息 / 加点"
        )
    if text == "更新日志":
        return "目前只是做了个框架，需要继续迁移副本、商城、排行等内容。"
    if text == "玩法":
        return "当前已迁移角色注册、改名、个人信息、经验、樱币、加点、恢复等基础玩法。"
    if text.startswith("注册"):
        name = text[2:].strip()
        if not name:
            return "要有名字哦！"
        if player:
            return "已有角色，无法创建！"
        player = service.register_player(user_id, name[:10])
        return f"已创建角色【{player.name}】！"
    if player is None:
        return None
    if text.startswith("改名"):
        return service.rename_player(player, text[2:].strip()[:10])
    if text == "个人信息":
        return service.build_profile_summary(player)
    if match := re.match(r"^加经验([0-9]+)$", text):
        return service.add_exp(player, int(match.group(1)))
    if match := re.match(r"^嘤([0-9]+)$", text):
        return service.add_money(player, int(match.group(1)))
    if text in {"恢复", "回复"}:
        return service.reset_player(player)
    if match := re.match(r"^加([0-9]+)(力量|智力|体质|敏捷|魅力)$", text):
        return service.add_points(player, match.group(2), int(match.group(1)))
    return None


def get_workspace_root() -> Path:
    astrbot_root = os.environ.get("ASTRBOT_ROOT", "").strip()
    if astrbot_root:
        return Path(astrbot_root).resolve().parents[1]
    return Path.cwd().resolve()


def get_astrbot_data_root() -> Path:
    astrbot_root = os.environ.get("ASTRBOT_ROOT", "").strip()
    if astrbot_root:
        return Path(astrbot_root).resolve() / "data"
    return get_workspace_root() / "data" / "astrbot" / "data"


def get_qqbot_runtime_root() -> Path:
    return get_astrbot_data_root() / "plugin_data" / "qqbot_features_runtime"


def get_qqbot_config_root() -> Path:
    return get_astrbot_data_root() / "plugin_data" / "qqbot_features_config"


def get_menu_image_cache_root() -> Path:
    return get_plugin_temp_root("menu")


def get_sub2api_usage_image_cache_root() -> Path:
    return get_plugin_temp_root("sub2api-usage")


def get_codexradar_efficiency_image_cache_root() -> Path:
    return get_plugin_temp_root("codexradar-efficiency")


def get_qqbot_config_value(section: str, key: str, default: str = "") -> str:
    config = load_qqbot_migrated_config()
    raw_section = config.get(section, {})
    if not isinstance(raw_section, dict):
        return default
    value = raw_section.get(key, default)
    if isinstance(value, (dict, list)):
        return default
    return str(value)


def load_qqbot_migrated_config() -> dict:
    config_path = get_qqbot_config_root() / "qqbot.toml"
    if not config_path.is_file():
        return {}
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def read_event_time_seconds(event: AstrMessageEvent) -> int:
    raw = _raw_event_dict(event)
    value = raw.get("time")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return int(time.time())


def resolve_display_name(group_id: int | str, user_id: int | str) -> str:
    return GroupNicknameStore(get_qqbot_runtime_root()).resolve_display_name(group_id, user_id)


def get_player_name(event: AstrMessageEvent) -> str:
    return resolve_display_name(event.get_group_id(), event.get_sender_id())


def fetch_factorio_space_age_windows_links() -> tuple[
    FactorioDownloadLink,
    FactorioDownloadLink,
]:
    """Resolve current Space Age Windows links for both release channels.

    Returns:
        A pair ordered as the stable link followed by the experimental link.

    Raises:
        FactorioDownloadError: If credentials, versions, or either link cannot be resolved.
    """
    credentials = load_factorio_credentials()
    versions = fetch_space_age_versions()
    query = urlencode({"username": credentials.username, "token": credentials.token})
    links: list[FactorioDownloadLink] = []
    for version in versions:
        url = f"https://www.factorio.com/get-download/{version}/expansion/win64?{query}"
        request = Request(
            url,
            headers={"User-Agent": "qqbot-astrbot-factorio-download-link/1.0"},
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=30.0,
            ) as response:
                if 200 <= response.status < 300:
                    links.append(
                        FactorioDownloadLink(version=version, url=response.url)
                    )
                    continue
                raise FactorioDownloadError(
                    f"Factorio 下载接口返回 HTTP {response.status}"
                )
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "").strip()
                if location:
                    links.append(
                        FactorioDownloadLink(version=version, url=urljoin(url, location))
                    )
                    continue
            if exc.code in {401, 403}:
                raise FactorioDownloadError(
                    "Factorio 凭据无效或账号没有 Space Age 下载权限"
                ) from exc
            if exc.code == 404:
                raise FactorioDownloadError(
                    "Factorio 官网没有提供当前版本的 Space Age Windows 安装包"
                ) from exc
            raise FactorioDownloadError(f"Factorio 下载接口返回 HTTP {exc.code}") from exc
        except URLError as exc:
            raise FactorioDownloadError(f"无法连接 Factorio 下载接口：{exc.reason}") from exc
        except TimeoutError as exc:
            raise FactorioDownloadError("连接 Factorio 下载接口超时") from exc
    return links[0], links[1]


def fetch_space_age_versions() -> tuple[str, str]:
    """Fetch current Space Age versions for both release channels.

    Returns:
        A pair ordered as the stable version followed by the experimental version.

    Raises:
        FactorioDownloadError: If the release API fails or either version is missing.
    """
    request = Request(
        "https://factorio.com/api/latest-releases",
        headers={"User-Agent": "qqbot-astrbot-factorio-download-link/1.0"},
    )
    try:
        with build_opener().open(request, timeout=30.0) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise FactorioDownloadError(f"Factorio 版本接口返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise FactorioDownloadError(f"无法连接 Factorio 版本接口：{exc.reason}") from exc
    except TimeoutError as exc:
        raise FactorioDownloadError("连接 Factorio 版本接口超时") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FactorioDownloadError("Factorio 版本接口返回内容不是 JSON") from exc
    versions: list[str] = []
    for channel in ("stable", "experimental"):
        release = data.get(channel) if isinstance(data, dict) else None
        version = release.get("expansion") if isinstance(release, dict) else None
        if not isinstance(version, str) or not version.strip():
            raise FactorioDownloadError(
                f"Factorio 版本接口缺少 {channel}.expansion 版本号"
            )
        versions.append(version.strip())
    return versions[0], versions[1]


def load_factorio_credentials() -> FactorioCredentials:
    env_file_values = load_workspace_env_values()
    username = (os.environ.get("FACTORIO_USERNAME") or env_file_values.get("FACTORIO_USERNAME", "")).strip()
    token = (os.environ.get("FACTORIO_TOKEN") or env_file_values.get("FACTORIO_TOKEN", "")).strip()
    if not username or not token:
        raise FactorioDownloadError("缺少 FACTORIO_USERNAME 或 FACTORIO_TOKEN")
    return FactorioCredentials(username=username, token=token)


def load_workspace_env_values() -> dict[str, str]:
    env_path = get_qqbot_config_root() / ".env"
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values
