from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random


DIFFICULTY_LABELS = {
    0: "PST",
    1: "PRS",
    2: "FTR",
    3: "BYD",
    4: "ETR",
}


@dataclass(frozen=True, slots=True)
class ArcChart:
    song_id: str
    song_name: str
    artist: str
    bpm: str
    pack: str
    version: str
    difficulty_index: int
    difficulty_label: str
    rating: int
    rating_plus: bool
    chart_designer: str
    jacket_designer: str
    constant_value: float
    jacket_path: Path | None

    @property
    def constant_text(self) -> str:
        return f"{self.constant_value:.1f}"


class ArcService:
    def __init__(self, assets_root: Path) -> None:
        self.assets_root = Path(assets_root)
        self.chart_root = self.assets_root / "官谱"

    def recommend_chart_by_ptt(
        self,
        ptt: float,
        constant_cache: dict | None = None,
        picker=None,
    ) -> ArcChart:
        charts = self.load_charts(constant_cache=constant_cache)
        window_min, window_max = self._build_recommend_window(ptt)
        candidates = [
            chart for chart in charts if window_min <= chart.constant_value <= window_max
        ]
        if not candidates:
            target = max(1.0, ptt - 0.7)
            candidates = sorted(
                charts,
                key=lambda chart: (abs(chart.constant_value - target), -chart.constant_value),
            )[: min(10, len(charts))]
        if not candidates:
            raise ValueError("当前本地曲库中没有可推荐的谱面。")
        chooser = picker or random.choice
        return chooser(candidates)

    def build_recommendation_text(self, ptt: float, chart: ArcChart) -> str:
        lines = [
            f"PTT {ptt:.1f} 推荐：",
            f"{chart.song_name} [{chart.difficulty_label}]",
            f"曲师：{chart.artist}",
            f"定数：{chart.constant_text}",
            f"BPM：{chart.bpm}",
            f"谱师：{chart.chart_designer}",
        ]
        if chart.jacket_designer:
            lines.append(f"曲绘：{chart.jacket_designer}")
        if chart.pack:
            lines.append(f"曲包：{chart.pack}")
        if chart.version:
            lines.append(f"版本：{chart.version}")
        if chart.jacket_path is None:
            lines.append("曲绘文件：当前本地资源缺失")
        return "\n".join(lines)

    def load_charts(self, constant_cache: dict | None = None) -> list[ArcChart]:
        payload = json.loads(self._read_songlist_text())
        constants_by_song = (constant_cache or {}).get("songs", {})
        charts: list[ArcChart] = []
        for song in payload.get("songs", []):
            if song.get("deleted"):
                continue
            song_id = str(song.get("id", "")).strip()
            if not song_id:
                continue
            title_localized = song.get("title_localized", {})
            song_name = (
                title_localized.get("en")
                or title_localized.get("zh-Hans")
                or title_localized.get("zh-Hant")
                or song_id
            )
            for difficulty in song.get("difficulties", []):
                rating_class = int(difficulty.get("ratingClass", -1))
                if rating_class not in DIFFICULTY_LABELS:
                    continue
                rating = int(difficulty.get("rating", 0))
                if rating <= 0:
                    continue
                rating_plus = bool(difficulty.get("ratingPlus", False))
                constant_value = self._resolve_constant_value(
                    constants_by_song,
                    song_id,
                    rating_class,
                    rating,
                    rating_plus,
                )
                charts.append(
                    ArcChart(
                        song_id=song_id,
                        song_name=str(song_name),
                        artist=str(difficulty.get("artist") or song.get("artist") or "未知"),
                        bpm=str(difficulty.get("bpm") or song.get("bpm") or "未知"),
                        pack=str(song.get("set", "")),
                        version=str(difficulty.get("version") or song.get("version") or ""),
                        difficulty_index=rating_class,
                        difficulty_label=DIFFICULTY_LABELS[rating_class],
                        rating=rating,
                        rating_plus=rating_plus,
                        chart_designer=str(difficulty.get("chartDesigner") or "未知"),
                        jacket_designer=str(difficulty.get("jacketDesigner") or ""),
                        constant_value=constant_value,
                        jacket_path=self._resolve_jacket_path(song_id, rating_class),
                    )
                )
        return charts

    def build_recommendation_image_uri(self, chart: ArcChart) -> str | None:
        if chart.jacket_path is None:
            return None
        return chart.jacket_path.as_uri()

    def _build_recommend_window(self, ptt: float) -> tuple[float, float]:
        min_value = max(1.0, round(ptt - 2.0, 1))
        max_value = max(min_value, round(ptt - 0.5, 1))
        return min_value, max_value

    def _resolve_constant_value(
        self,
        constants_by_song: dict,
        song_id: str,
        rating_class: int,
        rating: int,
        rating_plus: bool,
    ) -> float:
        constants = constants_by_song.get(song_id, {}).get("constants", {})
        raw_value = constants.get(str(rating_class))
        if raw_value is not None:
            return float(raw_value)
        return float(rating) + (0.7 if rating_plus else 0.0)

    def _read_songlist_text(self) -> str:
        for candidate in (self.chart_root / "songlist", self.chart_root / "songlist.json"):
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise FileNotFoundError(f"未找到 Arcaea songlist：{self.chart_root}")

    def _resolve_jacket_path(self, song_id: str, difficulty_index: int) -> Path | None:
        difficulty_key = DIFFICULTY_LABELS[difficulty_index].lower()
        candidates = (
            self.chart_root / song_id,
            self.chart_root / f"dl_{song_id}",
            self.chart_root / song_id.removeprefix("dl_"),
        )
        for song_dir in candidates:
            if not song_dir.exists():
                continue
            for file_name in (
                f"1080_{difficulty_key}.jpg",
                f"{difficulty_key}.jpg",
                "1080_base.jpg",
                "base.jpg",
            ):
                path = song_dir / file_name
                if path.exists():
                    return path
        return None
