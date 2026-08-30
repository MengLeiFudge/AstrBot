from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file


@dataclass
class SakuraPlayer:
    qq: int
    name: str
    level: int = 1
    exp: int = 0
    max_exp: int = 100
    hp: int = 100
    max_hp: int = 100
    mp: int = 100
    max_mp: int = 100
    money: int = 0
    phy_atk: int = 20
    mag_atk: int = 20
    phy_def: int = 5
    mag_def: int = 5
    speed: int = 100
    points: int = 0
    strength: int = 0
    intelligence: int = 0
    constitution: int = 0
    agility: int = 0
    charm: int = 0


class SakuraService:
    def __init__(self, file_path: Path) -> None:
        self.file_path = Path(file_path)
        self.runtime_root = infer_runtime_root_from_path(self.file_path)
        self.legacy_players_path = self.runtime_root / "data" / "sakura" / "players.json"
        self.store = RuntimeJsonStore(self.runtime_root)
        self.players = self._load()

    def register_player(self, qq: int, name: str) -> SakuraPlayer:
        player = SakuraPlayer(qq=qq, name=name)
        self.players[str(qq)] = player
        self._save()
        return player

    def get_player(self, qq: int) -> SakuraPlayer | None:
        return self.players.get(str(qq))

    def rename_player(self, player: SakuraPlayer, new_name: str) -> str:
        player.name = new_name
        self._save()
        return f"已更改昵称为{new_name}"

    def add_exp(self, player: SakuraPlayer, amount: int) -> str:
        player.exp += amount
        while player.exp >= player.max_exp:
            player.exp -= player.max_exp
            player.level += 1
            player.max_exp += 100
            player.max_hp = player.hp = player.level * 100
            player.max_mp = player.mp = player.level * 100
            player.points += 5
        self._save()
        return f"获得经验{amount}"

    def add_money(self, player: SakuraPlayer, amount: int) -> str:
        player.money += amount
        self._save()
        return f"获得樱币{amount}"

    def add_points(self, player: SakuraPlayer, point_type: str, amount: int) -> str:
        if player.points < amount:
            return "剩余可分配点数不足"
        mapping = {
            "力量": "strength",
            "智力": "intelligence",
            "体质": "constitution",
            "敏捷": "agility",
            "魅力": "charm",
        }
        field = mapping[point_type]
        setattr(player, field, getattr(player, field) + amount)
        player.points -= amount
        self._save()
        return f"已为{point_type}加点{amount}"

    def reset_player(self, player: SakuraPlayer) -> str:
        player.hp = player.max_hp
        player.mp = player.max_mp
        self._save()
        return "状态已恢复"

    def build_profile_summary(self, player: SakuraPlayer) -> str:
        return (
            f"Lv.{player.level} {player.name}\n"
            f"生命：{player.hp}/{player.max_hp}\n"
            f"魔力：{player.mp}/{player.max_mp}\n"
            f"经验：{player.exp}/{player.max_exp}\n"
            f"樱币：{player.money}"
        )

    def _load(self) -> dict[str, SakuraPlayer]:
        raw = self.store.read_with_legacy(
            "sakura.players",
            {},
            lambda: self._load_legacy_players(),
        )
        return {key: SakuraPlayer(**value) for key, value in raw.items()}

    def _save(self) -> None:
        payload = {key: asdict(value) for key, value in self.players.items()}
        self.store.write("sakura.players", payload)

    def _load_legacy_players(self) -> dict[str, object] | None:
        for path in (self.file_path, self.legacy_players_path):
            if path.exists():
                return read_json_file(path, {})
        return None
