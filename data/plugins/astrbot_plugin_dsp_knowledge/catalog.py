from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re


CATALOG_VERSION = "dsp-major-mods-v1"
MAX_SOURCE_FILE_BYTES = 512_000
CHUNK_CONTENT_CHARS = 1_400
CHUNK_OVERLAP_CHARS = 160
SUPPORTED_EXTENSIONS = {
    ".cfg",
    ".cs",
    ".csproj",
    ".ini",
    ".json",
    ".md",
    ".props",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}
SKIPPED_DIRECTORY_NAMES = {
    ".codex",
    ".git",
    ".github",
    ".idea",
    ".run",
    ".vs",
    ".vscode",
    "__pycache__",
    "artifacts",
    "bin",
    "build",
    "dependencies",
    "dist",
    "lib",
    "node_modules",
    "obj",
    "packages",
    "packer",
    "plugins",
    "previews",
    "tests",
    "tools",
}
ALWAYS_SEARCH_GROUP_IDS = frozenset({"1035445959", "319567534"})
GENERAL_DSP_ALIASES = (
    "dyson sphere program",
    "dsp mod",
    "dsp模组",
    "dsp 模组",
    "戴森球计划",
    "戴森球模组",
    "戴森球mod",
)
NON_DSP_DOMAIN_ALIASES = (
    "factorio",
    "异星工厂",
    "太空时代",
    "shapez",
    "异形工厂",
)


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Describe one high-value mod and its authoritative source surfaces."""

    key: str
    display_name: str
    relative_root: str
    source_directories: tuple[str, ...]
    source_files: tuple[str, ...]
    aliases: tuple[str, ...]
    shard_count: int


@dataclass(frozen=True, slots=True)
class SourceShard:
    """One stable document unit uploaded to the AstrBot knowledge base."""

    key: str
    module_key: str
    module_name: str
    bucket: int
    digest: str
    chunks: tuple[str, ...]
    file_count: int


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    """Fully transformed source snapshot used by one incremental sync pass."""

    shards: tuple[SourceShard, ...]
    file_count: int
    source_bytes: int


MODULES = (
    ModuleSpec(
        key="fractionate-everything",
        display_name="万物分馏 / Fractionate Everything",
        relative_root="MLJ_DSPmods/FractionateEverything",
        source_directories=("src",),
        source_files=(
            "README.md",
            "CHANGELOG.md",
            "GAME_DESIGN.md",
            "GAME_DESIGN_SPEC.md",
            "FractionateEverything.csproj",
            "Assets/manifest.json",
        ),
        aliases=(
            "万物分馏",
            "fractionate everything",
            "fractionateeverything",
            "fractionator",
            "分馏",
            "转化塔",
            "记忆源点",
        ),
        shard_count=6,
    ),
    ModuleSpec(
        key="project-genesis",
        display_name="创世之书 / Project Genesis",
        relative_root="ProjectGenesis",
        source_directories=("src", "data", "preloader"),
        source_files=(
            "README.md",
            "README-For programmer.md",
            "CHANGELOG.md",
            "ProjectGenesis.csproj",
        ),
        aliases=("创世之书", "创世", "project genesis", "projectgenesis", "genesis book"),
        shard_count=6,
    ),
    ModuleSpec(
        key="orbital-ring",
        display_name="星环 / Project Orbital Ring",
        relative_root="OrbitalRing-MOD",
        source_directories=("src", "data", "preloader"),
        source_files=(
            "README.md",
            "README-For programmer.md",
            "CHANGELOG.md",
            "ProjectOrbitalRing.csproj",
        ),
        aliases=("星环", "orbital ring", "orbitalring", "project orbital ring", "休谟"),
        shard_count=8,
    ),
    ModuleSpec(
        key="more-mega-structures",
        display_name="更多巨构 / More Mega Structures",
        relative_root="DSPmod_MoreMegaStructures",
        source_directories=("MoreMegaStructure/MoreMegaStructure",),
        source_files=("README.md",),
        aliases=(
            "更多巨构",
            "巨构",
            "more mega structure",
            "moremegastructure",
            "mms",
            "恒星炮",
            "星际组装厂",
            "物质解压器",
        ),
        shard_count=3,
    ),
    ModuleSpec(
        key="they-come-from-void",
        display_name="深空来敌 / They Come From Void",
        relative_root="DSP_Battle",
        source_directories=("src", "Properties"),
        source_files=("README.md", "DSP_Battle.csproj", "manifest.json"),
        aliases=(
            "深空来敌",
            "深空来袭",
            "深空",
            "they come from void",
            "theycomefromvoid",
            "dsp battle",
            "tcfv",
            "元驱动",
            "功勋",
            "水滴",
        ),
        shard_count=5,
    ),
    ModuleSpec(
        key="project-eden",
        display_name="伊甸园 / Project Eden",
        relative_root="dysonsphereprogram-ProjectEden",
        source_directories=("ProjectEden/src", "ProjectEden/data", "ProjectEden.Preloader"),
        source_files=(
            "README.md",
            "mod特性.md",
            "mod_feature.md",
            "ProjectEden/CHANGELOG.md",
            "ProjectEden/manifest.json",
            "ProjectEden/ProjectEden.csproj",
        ),
        aliases=("伊甸园", "伊甸", "project eden", "projecteden"),
        shard_count=8,
    ),
)


def query_targets_dsp_knowledge(query: str, group_id: str = "") -> bool:
    """Return whether a chat query belongs to the shared DSP corpus.

    Args:
        query: Current user query, optionally including quoted context.
        group_id: Structured QQ group ID. Known mod groups bias otherwise unclassified queries.

    Returns:
        True when the query or group identifies DSP or one of the six indexed mods.
    """

    normalized = re.sub(r"\s+", " ", str(query or "").strip().casefold())
    if not normalized:
        return False
    aliases = GENERAL_DSP_ALIASES + tuple(alias for module in MODULES for alias in module.aliases)
    for alias in aliases:
        normalized_alias = alias.casefold()
        if re.fullmatch(r"[a-z0-9_. -]+", normalized_alias):
            if re.search(rf"(?<![a-z0-9_]){re.escape(normalized_alias)}(?![a-z0-9_])", normalized):
                return True
        elif normalized_alias in normalized:
            return True
    if any(alias in normalized for alias in NON_DSP_DOMAIN_ALIASES):
        return False
    if str(group_id).strip() in ALWAYS_SEARCH_GROUP_IDS:
        return True
    return bool(re.search(r"(?<![a-z0-9_])dsp(?![a-z0-9_])", normalized))


def build_catalog_snapshot(source_root: Path) -> CatalogSnapshot:
    """Read, normalize, chunk, and shard all configured mod sources.

    Args:
        source_root: Root directory containing the configured DSP repositories.

    Returns:
        Immutable snapshot with stable shard keys and content digests.

    Raises:
        FileNotFoundError: If the root or any required module directory is missing.
        ValueError: If a module contains no indexable source files.
        UnicodeError: If an included text file cannot be decoded safely.
    """

    root = source_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"DSP source root does not exist: {root}")

    shards: list[SourceShard] = []
    total_files = 0
    total_bytes = 0
    for module in MODULES:
        module_root = (root / module.relative_root).resolve()
        if not module_root.is_dir() or module_root.is_symlink():
            raise FileNotFoundError(f"DSP module source is unavailable: {module.relative_root}")
        try:
            module_root.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"DSP module source escapes the configured root: {module.relative_root}") from exc

        files = _discover_module_files(module_root, module)
        if not files:
            raise ValueError(f"DSP module has no indexable files: {module.key}")
        total_files += len(files)

        bucket_files: dict[int, list[tuple[str, str, tuple[str, ...], int]]] = defaultdict(list)
        for path in files:
            relative_path = path.relative_to(module_root).as_posix()
            display_path = f"{module.relative_root}/{relative_path}"
            text, byte_count = _read_source_text(path)
            total_bytes += byte_count
            parts = _split_text(text)
            if not parts:
                continue
            chunks = tuple(
                _format_chunk(module.display_name, display_path, index, len(parts), part)
                for index, part in enumerate(parts, start=1)
            )
            bucket = int.from_bytes(hashlib.sha256(relative_path.encode("utf-8")).digest()[:8], "big") % module.shard_count
            bucket_files[bucket].append((relative_path, text, chunks, byte_count))

        if not bucket_files:
            raise ValueError(f"DSP module produced no non-empty chunks: {module.key}")
        for bucket, entries in sorted(bucket_files.items()):
            digest = hashlib.sha256()
            digest.update(CATALOG_VERSION.encode("ascii"))
            digest.update(module.key.encode("utf-8"))
            digest.update(str(bucket).encode("ascii"))
            shard_chunks: list[str] = []
            for relative_path, text, chunks, _ in sorted(entries, key=lambda item: item[0].casefold()):
                digest.update(relative_path.encode("utf-8"))
                digest.update(b"\0")
                digest.update(hashlib.sha256(text.encode("utf-8")).digest())
                shard_chunks.extend(chunks)
            shards.append(
                SourceShard(
                    key=f"{module.key}:{bucket:02d}",
                    module_key=module.key,
                    module_name=module.display_name,
                    bucket=bucket,
                    digest=digest.hexdigest(),
                    chunks=tuple(shard_chunks),
                    file_count=len(entries),
                )
            )

    return CatalogSnapshot(shards=tuple(shards), file_count=total_files, source_bytes=total_bytes)


def _discover_module_files(module_root: Path, module: ModuleSpec) -> tuple[Path, ...]:
    files: dict[Path, None] = {}
    for relative_directory in module.source_directories:
        directory = (module_root / relative_directory).resolve()
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            directory.relative_to(module_root)
        except ValueError:
            continue
        for current_root, directory_names, file_names in os.walk(directory, followlinks=False):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name.casefold() not in SKIPPED_DIRECTORY_NAMES
                and not (Path(current_root) / name).is_symlink()
            )
            for file_name in sorted(file_names):
                path = Path(current_root) / file_name
                if _is_indexable_file(path):
                    files[path.resolve()] = None

    for relative_file in module.source_files:
        path = (module_root / relative_file).resolve()
        try:
            path.relative_to(module_root)
        except ValueError:
            continue
        if _is_indexable_file(path):
            files[path] = None
    return tuple(sorted(files, key=lambda path: path.as_posix().casefold()))


def _is_indexable_file(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        return False
    if path.name.casefold() in {"changelog-history.md", "test.cs", "todo.md"}:
        return False
    size = path.stat().st_size
    return 0 < size <= MAX_SOURCE_FILE_BYTES


def _read_source_text(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    if text is None:
        raise UnicodeError(f"Unable to decode indexed DSP source: {path.name}")
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if path.suffix.casefold() == ".json" and text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            text = json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=False)
    return text, len(raw)


def _split_text(text: str) -> tuple[str, ...]:
    normalized = text.strip()
    if not normalized:
        return ()
    chunks: list[str] = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + CHUNK_CONTENT_CHARS, length)
        if end < length:
            lower_bound = start + CHUNK_CONTENT_CHARS // 2
            paragraph_break = normalized.rfind("\n\n", lower_bound, end)
            line_break = normalized.rfind("\n", lower_bound, end)
            if paragraph_break >= lower_bound:
                end = paragraph_break
            elif line_break >= lower_bound:
                end = line_break
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        next_start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
        newline = normalized.find("\n", next_start, end)
        start = newline + 1 if newline >= 0 else next_start
    return tuple(chunks)


def _format_chunk(module_name: str, source_path: str, index: int, total: int, content: str) -> str:
    return (
        f"DSP 模组: {module_name}\n"
        f"源码路径: {source_path}\n"
        f"文件分块: {index}/{total}\n\n"
        f"{content}"
    )
