from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASTRBOT_DATA = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "deployment" / "config-examples"
STALE_PLUGIN_EXAMPLE_NAMES = {
    "astrbot_plugin_qqbot_context_bridge.example.json",
    "astrbot_plugin_reply_style_guard.example.json",
    "astrbot_plugin_rightcodes_draw.example.json",
    "astrbot_plugin_source_knowledge.example.json",
    "meme_manager.example.json",
}
STALE_ROOT_EXAMPLE_NAMES = {
    "meme-manager.example.json",
}

DROP_KEYS = {
    "api_base",
    "base_url",
    "custom_extra_body",
    "custom_headers",
    "default_image_caption_provider_id",
    "default_provider_id",
    "embedding_api_base",
    "embedding_model",
    "fallback_chat_models",
    "fallback_order",
    "image_caption_provider_id",
    "llm_compress_provider_id",
    "llm_provider_id",
    "model",
    "model_name",
    "provider",
    "provider_id",
    "provider_pool",
    "provider_source_id",
    "provider_sources",
    "provider_settings",
    "provider_type",
    "providers",
    "reasoning",
    "router_system_prompt",
    "service_tier",
    "t2i_endpoint",
    "websearch_provider",
}
SECRET_KEY_FRAGMENTS = (
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "jwt_secret",
    "key",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
    "totp_secret",
)
PLACEHOLDER = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Export sanitized AstrBot runtime config examples.")
    parser.add_argument("--astrbot-data", type=Path, default=DEFAULT_ASTRBOT_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    export_examples(args.astrbot_data, args.output_dir)
    return 0


def export_examples(astrbot_data: Path, output_dir: Path) -> None:
    astrbot_data = astrbot_data.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd_config_path = astrbot_data / "cmd_config.json"
    if cmd_config_path.is_file():
        write_json(output_dir / "cmd_config.example.json", sanitize_config(read_json(cmd_config_path)))

    plugin_config_root = astrbot_data / "config"
    if plugin_config_root.is_dir():
        plugin_output = output_dir / "plugins"
        plugin_output.mkdir(parents=True, exist_ok=True)
        remove_stale_examples(plugin_output, STALE_PLUGIN_EXAMPLE_NAMES)
        for config_path in sorted(plugin_config_root.glob("*.json")):
            if config_path.name.startswith("abconf_"):
                continue
            output_path = plugin_output / config_path.name.replace("_config.json", ".example.json")
            write_json(output_path, sanitize_config(read_json(config_path)))
    remove_stale_examples(output_dir, STALE_ROOT_EXAMPLE_NAMES)

    database_path = astrbot_data / "data_v4.db"
    if database_path.is_file():
        write_json(output_dir / "personas.example.json", export_personas(database_path))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_stale_examples(directory: Path, names: set[str]) -> None:
    for name in names:
        path = directory / name
        if path.is_file():
            path.unlink()


def export_personas(database_path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            select persona_id, system_prompt, begin_dialogs, tools, skills, custom_error_message, sort_order
            from personas
            where persona_id = '云栖'
            order by sort_order, persona_id
            """
        ).fetchall()
    finally:
        connection.close()
    personas: list[dict[str, Any]] = []
    for row in rows:
        personas.append(
            {
                "persona_id": row["persona_id"],
                "system_prompt": row["system_prompt"],
                "begin_dialogs": parse_json_field(row["begin_dialogs"]),
                "tools": parse_json_field(row["tools"]),
                "skills": parse_json_field(row["skills"]),
                "custom_error_message": row["custom_error_message"],
                "sort_order": row["sort_order"],
            }
        )
    return personas


def parse_json_field(value: Any) -> Any:
    if value in (None, ""):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def sanitize_config(value: Any, *, key_path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = normalize_key(key)
            if should_drop_key(normalized_key):
                continue
            if is_secret_key(normalized_key):
                sanitized[key] = PLACEHOLDER
                continue
            sanitized[key] = sanitize_config(child, key_path=(*key_path, normalized_key))
        return sanitized
    if isinstance(value, list):
        return [sanitize_config(item, key_path=key_path) for item in value]
    return value


def normalize_key(key: object) -> str:
    return str(key or "").strip().lower()


def should_drop_key(key: str) -> bool:
    if key in DROP_KEYS:
        return True
    return key.endswith("_provider_id") or key.endswith("_model") or key.endswith("_api_base")


def is_secret_key(key: str) -> bool:
    return any(fragment in key for fragment in SECRET_KEY_FRAGMENTS)


if __name__ == "__main__":
    raise SystemExit(main())
