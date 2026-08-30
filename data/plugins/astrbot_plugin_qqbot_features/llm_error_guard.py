"""Classify group LLM failures and rate-limit private operator notices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import re
import time


LLM_ERROR_PREFIX = "LLM 响应错误:"
LLM_ERROR_NOTICE_COOLDOWN_SECONDS = 600.0
_MAX_NORMALIZED_ERROR_CHARS = 1000

_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[^\s,;]+"),
    re.compile(
        r"(?i)(?:\"|')?(?:api[_-]?key|access[_-]?token|authorization|token|secret|password)"
        r"(?:\"|')?\s*[:=]\s*(?:bearer\s+)?(?:\"|')?[^\s,;&}\"']+(?:\"|')?"
    ),
)
_VOLATILE_PATTERNS = (
    re.compile(r"(?i)\b(?:request|trace|correlation)[_-]?id\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
)
_ERROR_CLASS_PATTERN = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b")
_HTTP_STATUS_PATTERNS = (
    re.compile(r"(?i)\bHTTP(?:\s+status)?\s*[:=]?\s*([1-5][0-9]{2})\b"),
    re.compile(r"(?i)\bstatus(?:[_ ]code)?\s*[:=]\s*([1-5][0-9]{2})\b"),
)
_ERROR_SUMMARIES = {
    "apitimeouterror": ("APITimeoutError", "上游请求超时"),
    "timeouterror": ("TimeoutError", "上游请求超时"),
    "apiconnectionerror": ("APIConnectionError", "上游连接失败"),
    "connectionerror": ("ConnectionError", "上游连接失败"),
    "authenticationerror": ("AuthenticationError", "上游鉴权失败"),
    "permissiondeniederror": ("PermissionDeniedError", "上游拒绝访问"),
    "ratelimiterror": ("RateLimitError", "上游限流"),
    "badrequesterror": ("BadRequestError", "上游拒绝请求参数"),
    "notfounderror": ("NotFoundError", "上游资源不存在"),
    "conflicterror": ("ConflictError", "上游请求冲突"),
    "unprocessableentityerror": ("UnprocessableEntityError", "上游无法处理请求"),
    "internalservererror": ("InternalServerError", "上游服务内部错误"),
    "apistatuserror": ("APIStatusError", "上游返回异常状态"),
    "emptymodeloutputerror": ("EmptyModelOutputError", "模型返回空结果"),
}


@dataclass(frozen=True, slots=True)
class LlmErrorNotice:
    """A credential-safe owner notice and its process-local deduplication key."""

    key: str
    category: str
    message: str


class LlmErrorNoticeCooldown:
    """Claim normalized LLM issues at most once within a monotonic time window."""

    def __init__(
        self,
        cooldown_seconds: float = LLM_ERROR_NOTICE_COOLDOWN_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an in-memory limiter whose claims are shared by one plugin instance."""
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._claimed_at: dict[str, float] = {}

    def claim(self, key: str) -> bool:
        """Claim an issue synchronously so concurrent callbacks cannot both notify."""
        now = self._clock()
        cutoff = now - self._cooldown_seconds
        self._claimed_at = {
            claimed_key: claimed_at
            for claimed_key, claimed_at in self._claimed_at.items()
            if claimed_at > cutoff
        }
        claimed_at = self._claimed_at.get(key)
        if claimed_at is not None and now - claimed_at < self._cooldown_seconds:
            return False
        self._claimed_at[key] = now
        return True


def sanitize_llm_error_text(text: str) -> str:
    """Remove credential-like and volatile values before deriving a fallback key."""
    sanitized = " ".join(str(text or "").split())
    for pattern in _CREDENTIAL_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    for pattern in _VOLATILE_PATTERNS:
        sanitized = pattern.sub("[VOLATILE]", sanitized)
    return sanitized[:_MAX_NORMALIZED_ERROR_CHARS]


def build_llm_error_notice(
    text: str,
    *,
    self_id: str,
    group_id: str,
) -> LlmErrorNotice | None:
    """Build a safe notice only for AstrBot's Core-generated LLM error result."""
    normalized = " ".join(str(text or "").split())
    if not normalized.startswith(LLM_ERROR_PREFIX):
        return None

    sanitized = sanitize_llm_error_text(normalized)
    classes = _extract_error_classes(sanitized)
    status = _extract_http_status(sanitized)
    category, summary, key = _describe_error(classes, status, sanitized)
    message = (
        "AstrBot LLM 异常通知\n"
        f"机器人 QQ: {str(self_id or '未知').strip() or '未知'}\n"
        f"来源群: {str(group_id or '未知').strip() or '未知'}\n"
        f"错误类型: {category}\n"
        f"摘要: {summary}"
    )
    return LlmErrorNotice(key=key, category=category, message=message)


def _extract_error_classes(text: str) -> tuple[str, ...]:
    """Return stable exception class names without provider message details."""
    by_key: dict[str, str] = {}
    for match in _ERROR_CLASS_PATTERN.finditer(text):
        raw_name = match.group(1)
        key = raw_name.casefold()
        display = _ERROR_SUMMARIES.get(key, (raw_name, ""))[0]
        by_key.setdefault(key, display)
    return tuple(by_key[key] for key in sorted(by_key))


def _extract_http_status(text: str) -> str:
    """Extract a safe HTTP status discriminator when Core includes one."""
    for pattern in _HTTP_STATUS_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def _describe_error(
    classes: tuple[str, ...],
    status: str,
    sanitized: str,
) -> tuple[str, str, str]:
    """Map exception classes to a stable category, summary, and deduplication key."""
    if not classes:
        digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16]
        return "UnknownLlmError", "未分类的 LLM 上游调用失败", f"unknown:{digest}"

    summaries: list[str] = []
    for class_name in classes:
        summary = _ERROR_SUMMARIES.get(class_name.casefold(), (class_name, "LLM 上游调用失败"))[1]
        if summary not in summaries:
            summaries.append(summary)
    category = "+".join(classes)
    key = "classes:" + "+".join(class_name.casefold() for class_name in classes)
    if status:
        category = f"{category} (HTTP {status})"
        key = f"{key}:http-{status}"
        if summaries == ["上游返回异常状态"]:
            summaries = [f"上游返回 HTTP {status}"]
    return category, "；".join(summaries), key
