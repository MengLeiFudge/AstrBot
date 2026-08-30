from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..runtime_storage import RuntimeJsonStore
from ..runtime_storage import read_json_file
from .feature_catalog import FeatureDefinition
from .plugin_registry import list_visible_plugin_specs

GLOBAL_CONFIG_KEY = "__global__"


class SettingsStore:
    def __init__(self, data_root: Path, author_qq: int) -> None:
        self.data_root = Path(data_root)
        self.author_qq = author_qq
        self.settings_root = self.data_root / "settings"
        self.func_state_root = self.settings_root / "func_state"
        self.store = RuntimeJsonStore(self.data_root)

    def set_bot_admin(self, qq: int, is_admin: bool) -> None:
        return

    def is_bot_admin(self, qq: int) -> bool:
        return qq == self.author_qq

    def is_bot_admin_or_self(self, qq: int, self_id: int | str | None) -> bool:
        if self_id is not None and str(qq) == str(self_id):
            return True
        return self.is_bot_admin(qq)

    def list_bot_admins(self) -> dict[str, bool]:
        return {}

    def get_group_feature_state(self, group_id: int, feature: FeatureDefinition) -> bool:
        return self.get_plugin_enabled(feature.plugin_id)

    def set_group_feature_state(
        self,
        group_id: int,
        feature: FeatureDefinition,
        is_open: bool,
    ) -> None:
        self.set_plugin_enabled(feature.plugin_id, is_open)

    def get_group_feature_states(self, group_id: int) -> dict[str, bool]:
        return self.list_plugin_states()

    def get_plugin_enabled(self, plugin_id: str) -> bool:
        states = self._read_settings_state("plugin_state", {})
        return bool(states.get(plugin_id, True))

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        states = self._read_settings_state("plugin_state", {})
        states[plugin_id] = enabled
        self._write_settings_state("plugin_state", states)

    def list_plugin_states(self) -> dict[str, bool]:
        states = self._read_settings_state("plugin_state", {})
        return {
            spec.id: bool(states.get(spec.id, True))
            for spec in list_visible_plugin_specs()
        }

    def remove_group_scoped_settings(self, group_id: int | str) -> list[str]:
        group_key = str(group_id).strip()
        removed: list[str] = []
        if not group_key.isdigit():
            return removed

        func_state_namespace = f"settings.func_state.{group_key}"
        self.store.delete(func_state_namespace)
        if (self.func_state_root / f"{group_key}.json").exists():
            removed.append(func_state_namespace)

        for state_name in ("lolicon", "ai_proactive"):
            payload = self._read_settings_state(state_name, {})
            groups = payload.get("groups") if state_name == "ai_proactive" else None
            if isinstance(groups, dict) and group_key in groups:
                groups.pop(group_key, None)
                payload["groups"] = groups
                self._write_settings_state(state_name, payload)
                removed.append(f"settings.{state_name}:groups.{group_key}")
                continue
            if group_key in payload:
                payload.pop(group_key, None)
                self._write_settings_state(state_name, payload)
                removed.append(f"settings.{state_name}:{group_key}")
        return removed

    def get_reread_chance(self, group_id: int) -> float:
        chances = self._read_settings_state("reread", {})
        return float(self._global_or_legacy_group_value(chances, 0.05))

    def set_reread_chance(self, group_id: int, chance: float) -> None:
        chances = self._read_settings_state("reread", {})
        chances[GLOBAL_CONFIG_KEY] = chance
        self._write_settings_state("reread", chances)

    def get_thunder_config(self, group_id: int) -> tuple[float, int, int]:
        configs = self._read_settings_state("thunder", {})
        raw = self._global_or_legacy_group_value(
            configs,
            {"chance": 0.05, "min_seconds": 5, "max_seconds": 20},
        )
        return float(raw["chance"]), int(raw["min_seconds"]), int(raw["max_seconds"])

    def set_thunder_config(
        self,
        group_id: int,
        chance: float,
        min_seconds: int,
        max_seconds: int,
    ) -> None:
        configs = self._read_settings_state("thunder", {})
        configs[GLOBAL_CONFIG_KEY] = {
            "chance": chance,
            "min_seconds": min_seconds,
            "max_seconds": max_seconds,
        }
        self._write_settings_state("thunder", configs)

    def get_lolicon_config(self, group_id: int) -> tuple[bool, bool]:
        configs = self._read_settings_state("lolicon", {})
        raw = configs.get(str(group_id), {"group_r18": False, "show_image": False})
        return bool(raw["group_r18"]), bool(raw["show_image"])

    def set_lolicon_config(self, group_id: int, group_r18: bool, show_image: bool) -> None:
        configs = self._read_settings_state("lolicon", {})
        configs[str(group_id)] = {
            "group_r18": group_r18,
            "show_image": show_image,
        }
        self._write_settings_state("lolicon", configs)

    def _read_settings_state(self, name: str, default: dict[str, object]) -> dict[str, object]:
        path = self.settings_root / f"{name}.json"
        return self.store.read_with_legacy(
            f"settings.{name}",
            default,
            lambda: read_json_file(path, default) if path.exists() else None,
        )

    def _write_settings_state(self, name: str, payload: dict[str, object]) -> None:
        self.store.write(f"settings.{name}", payload)

    def _global_or_legacy_group_value(
        self,
        payload: dict[str, object],
        default: object,
    ) -> object:
        if GLOBAL_CONFIG_KEY in payload:
            return payload[GLOBAL_CONFIG_KEY]
        for key in sorted(payload):
            if str(key).isdigit():
                return payload[key]
        return default


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_strings(str(item).strip() for item in value)


def _dedupe_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
