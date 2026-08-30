from __future__ import annotations

from dataclasses import dataclass

from .plugin_registry import (
    PluginSpec,
    get_plugin_spec_by_menu_key,
    list_visible_plugin_specs,
)


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    plugin_id: str
    name: str
    aliases: tuple[str, ...] = ()
    menu_lines: tuple[str, ...] = ()
    menu_keys: tuple[str, ...] = ()
    admin_only: bool = False


def _feature_from_plugin(spec: PluginSpec) -> FeatureDefinition:
    return FeatureDefinition(
        plugin_id=spec.id,
        name=spec.name,
        aliases=spec.aliases,
        menu_lines=spec.menu_lines,
        menu_keys=spec.menu_keys,
        admin_only=spec.admin_only,
    )


def list_visible_features() -> list[FeatureDefinition]:
    return [_feature_from_plugin(spec) for spec in list_visible_plugin_specs()]


def get_feature_by_menu_key(key: str) -> FeatureDefinition | None:
    spec = get_plugin_spec_by_menu_key(key)
    if spec is None:
        return None
    return _feature_from_plugin(spec)


def build_group_menu_text(feature_states: dict[str, bool]) -> str:
    lines = ["当前插件模块如下："]
    for feature in list_visible_features():
        status = "开启" if feature_states.get(feature.plugin_id, False) else "关闭"
        lines.append(f"{feature.name}：{status}")
    lines.append("tips：【菜单+模块名称】获得对应功能菜单，如【菜单Arc】")
    return "\n".join(lines)


def build_feature_menu_text(key: str) -> str | None:
    feature = get_feature_by_menu_key(key)
    if feature is None:
        return None

    if not feature.menu_lines:
        return f"{feature.name} 暂无单独功能菜单。"

    lines = [f"{feature.name} 功能菜单："]
    lines.extend(feature.menu_lines)
    return "\n".join(lines)
