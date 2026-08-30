from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Iterable

from astrbot.api import logger


DEFAULT_MAX_RESULTS = 4
DEFAULT_MAX_CHARS = 2600
DEFAULT_MAX_FILES_PER_DOMAIN = 80
DEFAULT_MAX_FILE_BYTES = 220_000
DEFAULT_REFRESH_SECONDS = 600
MIN_EFFECTIVE_MAX_RESULTS = 2
MIN_EFFECTIVE_MAX_CHARS = 1200
MIN_EFFECTIVE_MAX_FILE_BYTES = 80_000
MIN_SCORE = 5.0
CONTEXT_LINES = 2
MIN_SCAN_FILES_PER_DOMAIN = 32
MIN_PATH_CANDIDATES_PER_ROOT = 80
MAX_PATH_CANDIDATES_PER_ROOT = 240
RG_TIMEOUT_SECONDS = 3.0
MAX_RG_TERMS = 14
RG_PRIMARY_TERM_COUNT = 5
MAX_RG_MATCH_EVENTS = 240
MAX_RG_UNIQUE_FILES = 80
SUPPORTED_EXTENSIONS = {
    ".cs",
    ".lua",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".xml",
    ".cfg",
    ".ini",
    ".py",
    ".ts",
    ".js",
}
SKIP_DIR_NAMES = {
    ".git",
    ".codex",
    ".idea",
    ".vs",
    ".vscode",
    ".github",
    ".yarn",
    "__pycache__",
    "bin",
    "obj",
    "packages",
    "node_modules",
    "assets",
    "audio",
    "logs",
    "log",
    "cache",
    "temp",
    "tmp",
    "dist",
    "build",
    "build1",
    "built-temp",
    "coverage",
    "devtools",
    "electron",
    "electron_gog",
    "electron_wegame",
    "gulp",
    "locales",
    "locale",
    "modzips",
    "out",
    "packer",
    "plugins",
    "preloader",
    "res",
    "res_built",
    "res_raw",
    "target",
    "textures",
    "translations",
}
SENSITIVE_NAME_MARKERS = {
    ".env",
    "token",
    "secret",
    "credential",
    "password",
    "cookie",
    "session",
    "login",
}
NOISY_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "tsconfig.tsbuildinfo",
}
GENERIC_RG_TERMS = {
    "dsp",
    "fe",
    "lua",
    "spz",
    "ring",
    "dyson",
    "vanilla",
    "shapez",
    "factorio",
}
BROAD_RG_TERMS = {
    "code",
    "display",
    "key",
    "mod",
    "mods",
    "tool",
    "tools",
    "shape",
    "shapes",
}
DOMAIN_GROUPS = {
    "1035445959": ("orbital-ring",),
    "319567534": ("fractionate-everything",),
    "1163635014": ("shapez",),
}
DEFAULT_ROOTS = (
    ("dsp-vanilla", "D:/project/dsp/DSPCore/DSPCore"),
    ("dsp-vanilla", "D:/project/dsp/MLJ_DSPmods/gamedata/DecompiledSource/Assembly-CSharp"),
    ("fractionate-everything", "D:/project/dsp/MLJ_DSPmods/FractionateEverything/src"),
    ("fractionate-everything", "D:/project/dsp/MLJ_DSPmods/FractionateEverything/README.md"),
    ("fractionate-everything", "D:/project/dsp/MLJ_DSPmods/FractionateEverything/CHANGELOG.md"),
    ("fractionate-everything", "D:/project/dsp/MLJ_DSPmods/VanillaCurveSim/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/README.md"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/SaveDataExporter/README.md"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/SaveDataExporter/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/SaveDataExporter/SaveDataExporter.csproj"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/SaveDataExporter/Assets/manifest.json"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/UXAEnhance/README.md"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/UXAEnhance/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/UXAEnhance/UXAEnhance.csproj"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/UXAEnhance/Assets/manifest.json"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/AfterBuildEvent/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/AfterBuildEvent/AfterBuildEvent.csproj"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/GetDspData/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/GetDspData/GetDspData.csproj"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/GetDspData/Assets/manifest.json"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/VanillaCurveSim/src"),
    ("dsp-mod-tools", "D:/project/dsp/MLJ_DSPmods/VanillaCurveSim/VanillaCurveSim.csproj"),
    ("dsp-mod-tools", "D:/project/dsp/DSP_Mods/UXAssist/README.md"),
    ("dsp-mod-tools", "D:/project/dsp/DSP_Mods/UXAssist/UXAssist.cs"),
    ("dsp-mod-tools", "D:/project/dsp/DSP_Mods/UXAssist/UIConfigWindow.cs"),
    ("orbital-ring", "D:/project/dsp/OrbitalRing-MOD/src"),
    ("orbital-ring", "D:/project/dsp/OrbitalRing-MOD/data"),
    ("orbital-ring", "D:/project/dsp/OrbitalRing-MOD/README.md"),
    ("orbital-ring", "D:/project/dsp/OrbitalRing-MOD/CHANGELOG.md"),
    ("orbital-ring", "D:/project/dsp/MLJ_DSPmods/gamedata/DecompiledSource/ProjectOrbitalRing"),
    ("project-genesis", "D:/project/dsp/ProjectGenesis/src"),
    ("project-genesis", "D:/project/dsp/ProjectGenesis/data"),
    ("project-genesis", "D:/project/dsp/ProjectGenesis/README.md"),
    ("project-genesis", "D:/project/dsp/ProjectGenesis/CHANGELOG.md"),
    ("project-genesis", "D:/project/dsp/MLJ_DSPmods/gamedata/DecompiledSource/ProjectGenesis"),
    ("shapez", "D:/project/shapez/shapez.io/src/js"),
    ("shapez", "D:/project/shapez/shapez.io/README.md"),
    ("shapez", "D:/project/shapez/shapez.io-cn/src/js"),
    ("shapez", "D:/project/shapez/shapez.io-cn/README.md"),
    ("shapez", "D:/project/shapez/shapez-mods/src"),
    ("shapez", "D:/project/shapez/shapezPathAnalyzer/shapezAnalyzer"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/DynamicInventory/src"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/expend-toolbar/src"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/expend-toolbar/README.md"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/more-quality-scaling"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/quality-cycler/src"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/quality-cycler/README.md"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/section-autocraft/src"),
    ("factorio", "D:/project/factorio/MLJ_Factorio_Mods/ups_saving_quality_ships/src"),
)
DOMAIN_ALIASES = {
    "dsp-vanilla": (
        "戴森球",
        "戴森球计划",
        "dsp",
        "dyson",
        "vanilla",
        "原版",
        "物流塔",
        "分拣器",
        "黑雾",
    ),
    "fractionate-everything": (
        "万物分馏",
        "fe",
        "fractionate",
        "fractionator",
        "分馏",
        "分馏塔",
        "转化塔",
        "记忆源点",
        "增产点数",
        "数据中心",
        "黑雾",
    ),
    "dsp-mod-tools": (
        "mlj_dspmods",
        "mlj dspmods",
        "dsp-mod-tools",
        "dspmodtools",
        "辅助模组",
        "小工具",
        "工具模组",
        "savedataexporter",
        "save data exporter",
        "存档数据导出",
        "导出存档统计",
        "uxaenhance",
        "uxa enhance",
        "uxassist enhance",
        "uxassist",
        "afterbuildevent",
        "after build event",
        "构建发布",
        "本地发布",
        "getdspdata",
        "vanillacurvesim",
        "vanilla curve sim",
        "曲线模拟",
    ),
    "orbital-ring": (
        "星环",
        "orbital",
        "orbitalring",
        "ring",
        "二阶",
        "三阶",
        "休谟",
        "火箭",
    ),
    "project-genesis": (
        "创世",
        "创世之书",
        "genesis",
        "projectgenesis",
    ),
    "shapez": (
        "shapez",
        "spz",
        "异形工厂",
        "图形",
        "形状",
        "电路",
        "短代码",
        "流形",
    ),
    "factorio": (
        "factorio",
        "异星工厂",
        "蓝图",
        "传送带",
        "品质",
        "物流机器人",
        "lua",
    ),
}
CJK_STOP_TERMS = {
    "这个",
    "那个",
    "怎么",
    "什么",
    "为什么",
    "为啥",
    "可以",
    "现在",
    "一下",
    "是不是",
}
SEARCH_TERM_SYNONYMS = {
    "单路锁定": ("singlelock", "single lock", "locked output"),
    "单锁": ("singlelock", "single lock", "locked output"),
    "锁定": ("lock", "locked"),
    "三阶": ("third", "tier 3"),
    "三阶段": ("三阶", "third", "tier 3"),
    "二阶": ("second",),
    "二阶段": ("二阶", "second", "tier 2"),
    "功率": ("power",),
    "光度": ("luminosity", "power"),
    "系数": ("coefficient", "ratio"),
    "休谟": ("hume",),
    "数学率": ("mathematical", "rate"),
    "配方": ("recipe", "recipes"),
    "科技": ("tech", "technology"),
    "矩阵": ("matrix", "matrices"),
    "创世之书": ("projectgenesis", "genesis"),
    "星环": ("orbitalring", "orbital", "ring"),
    "万物分馏": ("fractionate", "fractionator", "fractionation"),
    "分馏": ("fractionate", "fractionator", "fractionation"),
    "转化塔": ("conversion", "fractionator"),
    "异形工厂": ("shapez", "shape"),
    "图形": ("shape", "shapes"),
    "形状": ("shape", "shapes"),
    "短代码": ("blueprint", "bp", "code", "key"),
    "渲染": ("render", "display"),
    "蓝图": ("blueprint", "blueprints"),
    "品质": ("quality",),
    "异星工厂": ("factorio",),
    "存档数据导出": ("savedataexporter", "save data exporter"),
    "导出存档统计": ("savedataexporter", "save data exporter"),
    "构建发布": ("afterbuildevent", "after build event"),
    "本地发布": ("afterbuildevent", "after build event"),
}
SEARCH_SYNONYM_VALUES = {
    str(synonym).strip().lower()
    for synonyms in SEARCH_TERM_SYNONYMS.values()
    for synonym in synonyms
}
PRECISE_SEARCH_TERMS = {
    "savedataexporter",
    "save data exporter",
    "uxaenhance",
    "uxa enhance",
    "uxassist",
    "uxassist enhance",
    "afterbuildevent",
    "after build event",
    "getdspdata",
    "vanillacurvesim",
    "vanilla curve sim",
    "数学率引擎",
    "引力系数",
    "三阶段系数",
}
HIGH_VALUE_SEARCH_TERMS = set(SEARCH_TERM_SYNONYMS) | {
    "数学率引擎",
    "引力系数",
    "三阶段",
    "二阶段",
    "休谟",
    "系数",
    "光度",
    "功率",
}
BROAD_SCORE_TERMS = {
    "dsp",
    "dyson",
    "vanilla",
    "fe",
    "fractionate",
    "fractionator",
    "orbital",
    "orbitalring",
    "ring",
    "genesis",
    "projectgenesis",
    "shapez",
    "factorio",
    "mod",
    "mods",
    "tool",
    "tools",
    "源码",
    "模组",
}
NOISE_SEARCH_TERMS = {
    "是什么",
    "是什么啊",
    "都是什么",
    "都是什么啊",
    "什么啊",
    "干什么",
    "干什么的",
    "不会",
    "不会是",
    "直接",
    "直接加",
    "加到",
    "在哪",
    "哪里",
    "哪些",
    "影响",
    "东西",
    "那个",
    "这个",
    "哪了",
    "加到哪",
    "到哪了",
}
NOISE_SEARCH_MARKERS = (
    "是什么",
    "什么啊",
    "干什么",
    "不会",
    "那个",
    "这个",
    "哪些",
    "东西",
)


@dataclass(frozen=True, slots=True)
class SourceRoot:
    domain: str
    configured_path: str
    path: Path


@dataclass(frozen=True, slots=True)
class SourcePath:
    domain: str
    configured_root: str
    path: Path
    display_path: str
    lower_path: str


@dataclass(frozen=True, slots=True)
class SourceFile:
    domain: str
    configured_root: str
    path: Path
    display_path: str
    text: str
    lower_text: str
    lower_path: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    domain: str
    display_path: str
    line_start: int
    line_end: int
    score: float
    excerpt: str


@dataclass(frozen=True, slots=True)
class SourceKnowledgeConfig:
    enabled_groups: set[str]
    roots: tuple[SourceRoot, ...]
    max_results: int
    max_chars: int
    max_files_per_domain: int
    max_file_bytes: int
    refresh_seconds: int


class SourceIndex:
    def __init__(self, config: SourceKnowledgeConfig) -> None:
        self.config = config
        self._paths_by_domain: dict[str, tuple[SourcePath, ...]] = {}
        self._file_by_path: dict[Path, SourceFile] = {}
        self._loaded_at_by_domain: dict[str, float] = {}
        self._rg_path = shutil.which("rg")

    def search(self, query: str, domains: tuple[str, ...]) -> tuple[SearchResult, ...]:
        terms = build_search_terms(query)
        if not terms or not domains:
            return ()
        search_domains = self._expand_domains_for_query(query, terms, domains)
        rg_rows = search_with_rg(self.config, self._rg_path, terms, search_domains)
        if rg_rows is not None:
            return rg_rows[: self.config.max_results]
        self._ensure_loaded(search_domains)
        rows: list[SearchResult] = []
        for domain in search_domains:
            domain_rows: list[SearchResult] = []
            scanned = 0
            source_paths = sorted(
                self._paths_by_domain.get(domain, ()),
                key=lambda source_path: source_path_sort_key(source_path, terms),
            )
            for source_path in source_paths:
                if scanned >= self.config.max_files_per_domain:
                    break
                source_file = self._get_source_file(source_path)
                scanned += 1
                if source_file is None:
                    continue
                score = score_source_file(source_file, terms)
                if score < MIN_SCORE:
                    continue
                line_start, line_end, excerpt = best_excerpt(source_file.text, terms)
                if not excerpt:
                    continue
                domain_rows.append(
                    SearchResult(
                        domain=source_file.domain,
                        display_path=source_file.display_path,
                        line_start=line_start,
                        line_end=line_end,
                        score=score,
                        excerpt=excerpt,
                    )
                )
                if (
                    scanned >= min(MIN_SCAN_FILES_PER_DOMAIN, self.config.max_files_per_domain)
                    and len(domain_rows) >= self.config.max_results
                ):
                    break
            logger.debug(
                "[SourceKnowledge] searched source domain: domain=%s scanned=%s results=%s",
                domain,
                scanned,
                len(domain_rows),
            )
            rows.extend(domain_rows)
        rows.sort(key=lambda row: (-row.score, row.domain, row.display_path, row.line_start))
        return tuple(rows[: self.config.max_results])

    def available_domains(self) -> tuple[str, ...]:
        domains = {root.domain for root in self.config.roots if root.path.is_dir() or root.path.is_file()}
        return tuple(sorted(domains))

    def _expand_domains_for_query(
        self,
        query: str,
        terms: tuple[str, ...],
        domains: tuple[str, ...],
    ) -> tuple[str, ...]:
        expanded = list(domains)
        matched_domains = domains_matching_query(query, terms)
        for domain in matched_domains:
            if domain not in expanded:
                expanded.insert(0, domain)
        if matched_domains:
            return tuple(dict.fromkeys(expanded))
        if has_precise_cross_domain_terms(terms):
            for domain in self.available_domains():
                if domain not in expanded:
                    expanded.append(domain)
        return tuple(dict.fromkeys(expanded))

    def _ensure_loaded(self, domains: tuple[str, ...]) -> None:
        now = time.monotonic()
        for domain in domains:
            loaded_at = self._loaded_at_by_domain.get(domain, 0.0)
            if domain in self._paths_by_domain and now - loaded_at < self.config.refresh_seconds:
                continue
            paths = tuple(load_source_paths(self.config, domains={domain}))
            self._paths_by_domain[domain] = paths
            self._loaded_at_by_domain[domain] = now
            self._file_by_path = {
                path: source_file
                for path, source_file in self._file_by_path.items()
                if source_file.domain != domain
            }
            logger.info("[SourceKnowledge] indexed source paths: domain=%s count=%s", domain, len(paths))

    def _get_source_file(self, source_path: SourcePath) -> SourceFile | None:
        cached = self._file_by_path.get(source_path.path)
        if cached is not None:
            return cached
        text = read_source_text(source_path.path)
        if not text:
            return None
        source_file = SourceFile(
            domain=source_path.domain,
            configured_root=source_path.configured_root,
            path=source_path.path,
            display_path=source_path.display_path,
            text=text,
            lower_text=normalize_text(text),
            lower_path=source_path.lower_path,
        )
        self._file_by_path[source_path.path] = source_file
        return source_file


def load_source_knowledge_config(config=None) -> SourceKnowledgeConfig:
    roots = parse_source_roots(get_config_value(config, "source_roots", ""))
    if not roots:
        roots = tuple(SourceRoot(domain, raw_path, resolve_source_path(raw_path)) for domain, raw_path in DEFAULT_ROOTS)
    return SourceKnowledgeConfig(
        enabled_groups=parse_group_ids(get_config_value(config, "enabled_groups", "")),
        roots=roots,
        max_results=clamp_int(
            get_config_value(config, "max_results", DEFAULT_MAX_RESULTS),
            default=DEFAULT_MAX_RESULTS,
            minimum=MIN_EFFECTIVE_MAX_RESULTS,
            maximum=6,
        ),
        max_chars=clamp_int(
            get_config_value(config, "max_chars", DEFAULT_MAX_CHARS),
            default=DEFAULT_MAX_CHARS,
            minimum=MIN_EFFECTIVE_MAX_CHARS,
            maximum=6000,
        ),
        max_files_per_domain=clamp_int(
            get_config_value(config, "max_files_per_domain", DEFAULT_MAX_FILES_PER_DOMAIN),
            default=DEFAULT_MAX_FILES_PER_DOMAIN,
            minimum=32,
            maximum=5000,
        ),
        max_file_bytes=clamp_int(
            get_config_value(config, "max_file_bytes", DEFAULT_MAX_FILE_BYTES),
            default=DEFAULT_MAX_FILE_BYTES,
            minimum=MIN_EFFECTIVE_MAX_FILE_BYTES,
            maximum=1_000_000,
        ),
        refresh_seconds=clamp_int(
            get_config_value(config, "refresh_seconds", DEFAULT_REFRESH_SECONDS),
            default=DEFAULT_REFRESH_SECONDS,
            minimum=30,
            maximum=86_400,
        ),
    )


def get_config_value(config, key: str, default):
    if config is None:
        return default
    try:
        return config.get(key, default)
    except Exception:
        return default


def parse_group_ids(raw: object) -> set[str]:
    if isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = str(raw or "").replace("，", ",").split(",")
    groups: set[str] = set()
    for value in values:
        group_id = str(value).strip()
        if group_id.isdigit():
            groups.add(group_id)
    return groups


def parse_source_roots(raw: object) -> tuple[SourceRoot, ...]:
    lines: list[str] = []
    if isinstance(raw, (list, tuple, set)):
        lines = [str(item) for item in raw]
    else:
        text = str(raw or "").replace("；", ";")
        for item in re.split(r"[\n;]+", text):
            if item.strip():
                lines.append(item)
    roots: list[SourceRoot] = []
    for line in lines:
        if "=" not in line:
            continue
        domain, raw_path = line.split("=", 1)
        domain = normalize_domain(domain)
        raw_path = raw_path.strip().strip('"')
        if domain and raw_path:
            roots.append(SourceRoot(domain, raw_path, resolve_source_path(raw_path)))
    return tuple(roots)


def resolve_source_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"')
    drive_match = re.match(r"^([A-Za-z]):[\\/](.*)$", cleaned)
    if drive_match:
        drive = drive_match.group(1).lower()
        suffix = drive_match.group(2).replace("\\", "/")
        wsl_path = Path(f"/mnt/{drive}/{suffix}")
        if wsl_path.exists():
            return wsl_path
    return Path(cleaned).expanduser()


def normalize_domain(raw: object) -> str:
    domain = str(raw or "").strip().lower().replace("_", "-")
    aliases = {
        "dsp": "dsp-vanilla",
        "dyson-sphere-program": "dsp-vanilla",
        "fe": "fractionate-everything",
        "fractionateeverything": "fractionate-everything",
        "orbitalring": "orbital-ring",
        "project-orbital-ring": "orbital-ring",
        "genesis": "project-genesis",
        "projectgenesis": "project-genesis",
        "spz": "shapez",
        "dsp-tools": "dsp-mod-tools",
        "dspmodtools": "dsp-mod-tools",
        "mlj-dspmods": "dsp-mod-tools",
        "mlj-dspmods-tools": "dsp-mod-tools",
    }
    return aliases.get(domain, domain)


def clamp_int(raw: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def format_enabled_groups(enabled_groups: set[str]) -> str:
    return ",".join(sorted(enabled_groups)) if enabled_groups else "*"


def resolve_domains(group_id: str, query: str) -> tuple[str, ...]:
    domains: list[str] = list(domains_matching_query(query, build_search_terms(query)))
    for domain in DOMAIN_GROUPS.get(group_id, ()):
        domains.append(domain)
    return tuple(dict.fromkeys(domains))


def domains_matching_query(query: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    lowered = normalize_text(query)
    term_set = set(terms)
    domains: list[str] = []
    for domain, aliases in DOMAIN_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if not normalized_alias:
                continue
            if normalized_alias in lowered or normalized_alias in term_set:
                domains.append(domain)
                break
    return tuple(dict.fromkeys(domains))


def build_search_terms(query: str) -> tuple[str, ...]:
    lowered = normalize_text(query)
    terms: list[str] = []
    for aliases in DOMAIN_ALIASES.values():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if normalized_alias and normalized_alias in lowered:
                terms.append(normalized_alias)
    terms.extend(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}|[0-9]+", lowered))
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        if is_noise_search_term(seq):
            continue
        if len(seq) <= 10:
            terms.append(seq)
        terms.extend(cjk_ngrams(seq, 2, 4))
    for key, synonyms in SEARCH_TERM_SYNONYMS.items():
        if normalize_text(key) in lowered or key in terms:
            terms.append(key)
            terms.extend(synonyms)
    clean_terms: list[str] = []
    for term in terms:
        normalized = normalize_text(term)
        if len(normalized) < 2 or is_noise_search_term(normalized):
            continue
        clean_terms.append(normalized)
    clean_terms.sort(key=search_term_sort_key)
    return tuple(dict.fromkeys(clean_terms))[:48]


def search_term_sort_key(term: str) -> tuple[int, int, int, str]:
    if is_precise_search_term(term):
        return (0, -len(term), 0, term)
    if term in HIGH_VALUE_SEARCH_TERMS:
        return (1, -len(term), 0, term)
    if term in SEARCH_SYNONYM_VALUES:
        return (3, -len(term), 0, term)
    if contains_cjk(term):
        length = len(term)
        if 2 <= length <= 6:
            return (2, -length, 0, term)
        return (5, length, 0, term)
    if term in BROAD_SCORE_TERMS:
        return (8, -len(term), 0, term)
    return (4, -len(term), 0, term)


def is_noise_search_term(term: str) -> bool:
    normalized = normalize_text(term)
    if normalized in CJK_STOP_TERMS or normalized in NOISE_SEARCH_TERMS:
        return True
    return any(marker in normalized for marker in NOISE_SEARCH_MARKERS)


def has_precise_cross_domain_terms(terms: tuple[str, ...]) -> bool:
    return any(is_precise_search_term(term) for term in terms)


def is_precise_search_term(term: str) -> bool:
    normalized = normalize_text(term)
    if normalized in PRECISE_SEARCH_TERMS:
        return True
    if normalized in SEARCH_SYNONYM_VALUES:
        return False
    return False


def cjk_ngrams(text: str, minimum: int, maximum: int) -> Iterable[str]:
    length = len(text)
    for size in range(min(maximum, length), minimum - 1, -1):
        for index in range(0, max(0, length - size + 1)):
            yield text[index : index + size]


def normalize_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def search_with_rg(
    config: SourceKnowledgeConfig,
    rg_path: str | None,
    terms: tuple[str, ...],
    domains: tuple[str, ...],
) -> tuple[SearchResult, ...] | None:
    if not rg_path:
        return None
    rg_terms = select_rg_terms(terms)
    if not rg_terms:
        return ()
    rows: list[SearchResult] = []
    for domain in domains:
        roots = existing_roots_for_domain(config, domain)
        if not roots:
            continue
        for term_batch in rg_term_batches(rg_terms):
            cmd = build_rg_command(rg_path, term_batch, roots, config.max_file_bytes)
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=RG_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.debug("[SourceKnowledge] rg search skipped: domain=%s error=%s", domain, exc)
                continue
            if completed.returncode not in (0, 1):
                logger.debug(
                    "[SourceKnowledge] rg search failed: domain=%s code=%s stderr=%s",
                    domain,
                    completed.returncode,
                    completed.stderr[:240],
                )
                continue
            domain_rows = parse_rg_matches(domain, completed.stdout, terms, config.max_file_bytes)
            if domain_rows:
                rows.extend(domain_rows)
                if len(rows) >= config.max_results * 3:
                    break
    rows = dedupe_results(rows)
    rows.sort(key=lambda row: (-row.score, row.domain, row.display_path, row.line_start))
    return tuple(rows[: config.max_results])


def select_rg_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    for term in terms:
        if len(term) < 2:
            continue
        if term in GENERIC_RG_TERMS:
            continue
        if is_rg_noise_term(term):
            continue
        if contains_cjk(term) or len(term) >= 4:
            selected.append(term)
    selected.sort(key=rg_term_sort_key)
    return tuple(dict.fromkeys(selected))[:MAX_RG_TERMS]


def rg_term_batches(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if len(terms) <= RG_PRIMARY_TERM_COUNT:
        return (terms,)
    primary = terms[:RG_PRIMARY_TERM_COUNT]
    secondary = terms[RG_PRIMARY_TERM_COUNT:]
    return (primary, secondary)


def rg_term_sort_key(term: str) -> tuple[int, int, int, str]:
    if term in BROAD_RG_TERMS:
        return (8, -len(term), 0, term)
    if is_precise_search_term(term):
        return (0, -len(term), 0, term)
    if term in SEARCH_TERM_SYNONYMS:
        return (1, -len(term), 0, term)
    if contains_cjk(term):
        length = len(term)
        if 2 <= length <= 4:
            return (2, -length, 0, term)
        if length <= 6:
            return (3, -length, 0, term)
        return (6, length, 0, term)
    if term in SEARCH_SYNONYM_VALUES:
        return (5, -len(term), 0, term)
    return (7, -len(term), 0, term)


def is_rg_noise_term(term: str) -> bool:
    return (
        "怎么" in term
        or "为啥" in term
        or term in {"么算", "么处理", "处理", "一下", "这个", "那个"}
    )


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def existing_roots_for_domain(config: SourceKnowledgeConfig, domain: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    for root in config.roots:
        if root.domain == domain and (root.path.is_dir() or root.path.is_file()):
            roots.append(root.path)
    roots.sort(key=root_search_priority)
    return tuple(roots)


def root_search_priority(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    priority = 50
    if path.is_file() and name in {"readme.md", "changelog.md", "manifest.json"}:
        priority -= 30
    if name in {"data", "locale", "localization"} or parts & {"data", "locale", "localization"}:
        priority -= 24
    if path.is_file() and name.startswith(("strings", "tutorial")):
        priority -= 24
    if name in {"src", "source"} or parts & {"src", "source"}:
        priority -= 8
    if parts & {"decompiledsource"}:
        priority += 10
    return (priority, len(path.parts), path.as_posix().lower())


def build_rg_command(
    rg_path: str,
    terms: tuple[str, ...],
    roots: tuple[Path, ...],
    max_file_bytes: int,
) -> list[str]:
    cmd = [
        rg_path,
        "--json",
        "--fixed-strings",
        "--ignore-case",
        "--line-number",
        "--color",
        "never",
        "--max-count",
        "1",
        "--max-filesize",
        str(max_file_bytes),
    ]
    for extension in sorted(SUPPORTED_EXTENSIONS):
        cmd.extend(["--glob", f"*{extension}"])
    for dir_name in sorted(SKIP_DIR_NAMES):
        cmd.extend(["--glob", f"!**/{dir_name}/**"])
    for file_name in sorted(NOISY_FILE_NAMES):
        cmd.extend(["--glob", f"!**/{file_name}"])
    for term in terms:
        cmd.extend(["-e", term])
    cmd.extend(str(root) for root in roots)
    return cmd


def parse_rg_matches(
    domain: str,
    stdout: str,
    terms: tuple[str, ...],
    max_file_bytes: int,
) -> list[SearchResult]:
    rows: list[SearchResult] = []
    seen_files: set[Path] = set()
    match_events = 0
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "match":
            continue
        match_events += 1
        if match_events > MAX_RG_MATCH_EVENTS:
            break
        data = payload.get("data") or {}
        raw_path = ((data.get("path") or {}).get("text") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if not is_supported_source_file(path, max_file_bytes):
            continue
        if path not in seen_files and len(seen_files) >= MAX_RG_UNIQUE_FILES:
            continue
        seen_files.add(path)
        line_number = int(data.get("line_number") or 0)
        text = read_source_text(path)
        display_path = display_source_path(path)
        if text:
            source_file = SourceFile(
                domain=domain,
                configured_root="",
                path=path,
                display_path=display_path,
                text=text,
                lower_text=normalize_text(text),
                lower_path=normalize_text(display_path),
            )
            score = score_source_file(source_file, terms)
            line_start, line_end, excerpt = best_excerpt(source_file.text, terms)
        else:
            matched_line = (data.get("lines") or {}).get("text") or ""
            score = score_match_line(display_path, matched_line, terms)
            line_start = line_number
            line_end = line_number
            excerpt = trim_line(matched_line)
        if score < MIN_SCORE or not excerpt:
            continue
        rows.append(
            SearchResult(
                domain=domain,
                display_path=display_path,
                line_start=line_start,
                line_end=line_end,
                score=score,
                excerpt=excerpt,
            )
        )
    return rows


def score_match_line(display_path: str, line: str, terms: tuple[str, ...]) -> float:
    lower_path = normalize_text(display_path)
    lower_line = normalize_text(line)
    score = 0.0
    for term in terms:
        weight = term_weight(term)
        if term in lower_path:
            score += weight * 6.0
        if term in lower_line:
            score += weight * 2.0
    return score


def dedupe_results(rows: Iterable[SearchResult]) -> list[SearchResult]:
    best_by_key: dict[tuple[str, str, int], SearchResult] = {}
    for row in rows:
        key = (row.domain, row.display_path, row.line_start)
        existing = best_by_key.get(key)
        if existing is None or row.score > existing.score:
            best_by_key[key] = row
    return list(best_by_key.values())


def load_source_files(config: SourceKnowledgeConfig, *, domains: set[str] | None = None) -> list[SourceFile]:
    loaded: list[SourceFile] = []
    per_domain_count: dict[str, int] = {}
    for source_path in load_source_paths(config, domains=domains):
        current_count = per_domain_count.get(source_path.domain, 0)
        if current_count >= config.max_files_per_domain:
            continue
        text = read_source_text(source_path.path)
        if not text:
            continue
        loaded.append(
            SourceFile(
                domain=source_path.domain,
                configured_root=source_path.configured_root,
                path=source_path.path,
                display_path=source_path.display_path,
                text=text,
                lower_text=normalize_text(text),
                lower_path=source_path.lower_path,
            )
        )
        per_domain_count[source_path.domain] = current_count + 1
    return loaded


def load_source_paths(config: SourceKnowledgeConfig, *, domains: set[str] | None = None) -> list[SourcePath]:
    source_paths: list[SourcePath] = []
    path_limit_per_root = min(
        MAX_PATH_CANDIDATES_PER_ROOT,
        max(MIN_PATH_CANDIDATES_PER_ROOT, config.max_files_per_domain * 4),
    )
    for root in config.roots:
        if domains is not None and root.domain not in domains:
            continue
        if root.path.is_file():
            if is_supported_source_file(root.path, config.max_file_bytes):
                display_path = display_source_path(root.path)
                source_paths.append(
                    SourcePath(
                        domain=root.domain,
                        configured_root=root.configured_path,
                        path=root.path,
                        display_path=display_path,
                        lower_path=normalize_text(display_path),
                    )
                )
            continue
        if not root.path.is_dir():
            logger.debug("[SourceKnowledge] source root missing: domain=%s path=%s", root.domain, root.path)
            continue
        root_count = 0
        for path in iter_source_paths(root.path):
            if not is_supported_source_file(path, config.max_file_bytes):
                continue
            display_path = display_source_path(path)
            source_paths.append(
                SourcePath(
                    domain=root.domain,
                    configured_root=root.configured_path,
                    path=path,
                    display_path=display_path,
                    lower_path=normalize_text(display_path),
                )
            )
            root_count += 1
            if root_count >= path_limit_per_root:
                break
    source_paths.sort(key=source_path_base_sort_key)
    return source_paths


def iter_source_paths(root: Path) -> Iterable[Path]:
    for current_root, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(
            name
            for name in dir_names
            if not should_skip_dir(name)
        )
        for file_name in sorted(file_names):
            path = Path(current_root) / file_name
            yield path


def should_skip_dir(name: str) -> bool:
    lowered = name.lower()
    return lowered in SKIP_DIR_NAMES or lowered.endswith(".egg-info")


def is_supported_source_file(path: Path, max_file_bytes: int) -> bool:
    name = path.name.lower()
    if name in NOISY_FILE_NAMES:
        return False
    if any(marker in name for marker in SENSITIVE_NAME_MARKERS):
        return False
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > max_file_bytes:
            return False
    except OSError:
        return False
    return True


def source_path_sort_key(source_path: SourcePath, terms: tuple[str, ...]) -> tuple[float, int, int, str]:
    path_score = 0.0
    for term in terms:
        if term in source_path.lower_path:
            path_score += term_weight(term) * 6.0
    return (-path_score, source_path_priority(source_path.path), len(source_path.path.parts), source_path.lower_path)


def source_path_base_sort_key(source_path: SourcePath) -> tuple[int, int, str]:
    return (source_path_priority(source_path.path), len(source_path.path.parts), source_path.lower_path)


def source_path_priority(path: Path) -> int:
    name = path.name.lower()
    suffix = path.suffix.lower()
    parts = {part.lower() for part in path.parts}
    priority = 50
    if name in {"readme.md", "changelog.md", "manifest.json", "info.json"}:
        priority -= 24
    if name.startswith(("strings", "tutorial")):
        priority -= 22
    if parts & {"data", "locale", "localization"}:
        priority -= 18
    if suffix in {".json", ".toml", ".yaml", ".yml", ".xml"}:
        priority -= 12
    elif suffix in {".cs", ".lua"}:
        priority -= 10
    elif suffix in {".md", ".txt"}:
        priority -= 8
    elif suffix in {".ts", ".js", ".py"}:
        priority -= 6
    if parts & {"src", "source", "scripts"}:
        priority -= 8
    if parts & {"protos"}:
        priority -= 6
    if parts & {"docs", "doc", "examples", "mod_examples"}:
        priority += 8
    return priority


def read_source_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in raw[:4096]:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def display_source_path(path: Path) -> str:
    resolved = path.resolve()
    parts = resolved.parts
    if len(parts) >= 4 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        return f"{drive}:/" + "/".join(parts[3:])
    return resolved.as_posix()


def score_source_file(source_file: SourceFile, terms: tuple[str, ...]) -> float:
    score = 0.0
    precise_hits = 0
    for term in terms:
        weight = term_weight(term)
        if term in source_file.lower_path:
            score += weight * 6.0
            if is_precise_search_term(term):
                precise_hits += 1
        count = source_file.lower_text.count(term)
        if count:
            score += weight * min(count, 8)
            if is_precise_search_term(term):
                precise_hits += 1
    if precise_hits >= 2:
        score += 24.0
    elif precise_hits == 1:
        score += 10.0
    return score


def term_weight(term: str) -> float:
    if term in BROAD_SCORE_TERMS:
        return 0.4
    if is_precise_search_term(term):
        return 8.0
    if len(term) >= 6:
        return 4.0
    if len(term) >= 4:
        return 3.0
    if len(term) >= 2:
        return 2.0
    return 1.0


def best_excerpt(text: str, terms: tuple[str, ...]) -> tuple[int, int, str]:
    lines = text.splitlines()
    if not lines:
        return 0, 0, ""
    best_index = -1
    best_score = 0.0
    for index, line in enumerate(lines):
        lowered = normalize_text(line)
        line_score = sum(term_weight(term) for term in terms if term in lowered)
        if line_score and any(is_precise_search_term(term) and term in lowered for term in terms):
            line_score += 12.0
        if line_score > best_score:
            best_score = line_score
            best_index = index
    if best_index < 0:
        return 0, 0, ""
    start = max(0, best_index - CONTEXT_LINES)
    end = min(len(lines), best_index + CONTEXT_LINES + 1)
    excerpt_lines = [trim_line(line, terms=terms) for line in lines[start:end]]
    excerpt = "\n".join(line for line in excerpt_lines if line.strip())
    return start + 1, end, excerpt


def trim_line(line: str, limit: int = 220, terms: tuple[str, ...] = ()) -> str:
    clean = line.rstrip()
    if len(clean) <= limit:
        return clean
    start = best_trim_start(clean, terms, limit)
    end = min(len(clean), start + limit)
    prefix = "… " if start > 0 else ""
    suffix = " …（截断）" if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix


def best_trim_start(text: str, terms: tuple[str, ...], limit: int) -> int:
    lowered = normalize_text(text)
    candidates = {0}
    for term in terms:
        if len(term) < 2:
            continue
        index = lowered.find(term)
        while index >= 0:
            candidates.add(max(0, index - limit // 3))
            candidates.add(max(0, index - limit // 2))
            candidates.add(max(0, index - 20))
            index = lowered.find(term, index + 1)
    best_start = 0
    best_score = -1.0
    for start in candidates:
        snippet = normalize_text(text[start : start + limit])
        score = sum(term_weight(term) for term in terms if term in snippet)
        if "15000" in snippet:
            score += 8.0
        if "系数" in snippet:
            score += 6.0
        if "三阶" in snippet or "三阶段" in snippet:
            score += 4.0
        if score > best_score or (score == best_score and start < best_start):
            best_score = score
            best_start = start
    return best_start


def format_source_injection(results: tuple[SearchResult, ...], query: str, max_chars: int) -> str:
    if not results:
        return ""
    lines = [
        "源码知识库检索结果：以下片段来自本机只读源码树，只能作为本轮回答的证据。",
        "回答戴森球计划、万物分馏、MLJ_DSPmods 辅助模组/工具、星环、创世之书、shapez、Factorio 相关问题时，优先依据这些源码证据；证据不足就说源码证据不足，不要用通用游戏或其他模组经验补猜。",
        f"用户问题：{query}",
    ]
    for index, result in enumerate(results, 1):
        location = f"{result.display_path}:L{result.line_start}"
        if result.line_end > result.line_start:
            location += f"-L{result.line_end}"
        lines.append(
            f"[{index}] domain={result.domain} score={result.score:.1f} source={location}\n{result.excerpt}"
        )
    return trim_text("\n\n".join(lines), max_chars)


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 12)].rstrip() + "\n...（已截断）"
