from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file


EN_WIKI_API_URL = "https://arcaea.fandom.com/api.php"


def fetch_en_wiki_redirects(title: str) -> list[str]:
    query = urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "redirects",
            "rdlimit": "max",
            "format": "json",
        }
    )
    request = Request(
        f"{EN_WIKI_API_URL}?{query}",
        headers={"User-Agent": "qqbot/0.1"},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    pages = payload.get("query", {}).get("pages", {})
    redirects: list[str] = []
    for page in pages.values():
        redirects.extend(
            str(item.get("title", "")).strip()
            for item in page.get("redirects", [])
            if str(item.get("title", "")).strip()
        )
    return redirects


class ArcAliasService:
    def __init__(
        self,
        assets_root: Path,
        cache_path: Path,
        manual_alias_path: Path | None = None,
        wiki_redirect_fetcher=None,
    ) -> None:
        self.assets_root = Path(assets_root)
        self.chart_root = self.assets_root / "官谱"
        self.cache_path = Path(cache_path)
        self.manual_alias_path = Path(manual_alias_path) if manual_alias_path else self.cache_path.with_name(
            "guess_manual_aliases.json"
        )
        self.wiki_redirect_fetcher = wiki_redirect_fetcher or fetch_en_wiki_redirects
        self.runtime_root = infer_runtime_root_from_path(self.cache_path)
        self.legacy_cache_path = self.runtime_root / "data" / "arc" / self.cache_path.name
        self.legacy_manual_alias_path = self.runtime_root / "data" / "arc" / self.manual_alias_path.name
        self.store = RuntimeJsonStore(self.runtime_root)

    def build_alias_cache(self, now: datetime | None = None) -> dict:
        current = now or datetime.now()
        manual_aliases = self._load_manual_aliases()
        songs = {}
        for song in self._load_song_titles():
            aliases: list[str] = []
            for title in song["localized_titles"]:
                self._append_aliases(aliases, self._build_base_aliases(title))
                try:
                    wiki_aliases = self.wiki_redirect_fetcher(title)
                except Exception:
                    wiki_aliases = []
                self._append_aliases(aliases, wiki_aliases)
            self._append_aliases(aliases, manual_aliases.get(song["id"], []))
            songs[song["id"]] = {
                "title": song["title"],
                "aliases": aliases,
            }
        return {
            "updated_at": current.isoformat(),
            "songs": songs,
        }

    def sync_alias_cache(self, now: datetime | None = None) -> dict:
        payload = self.build_alias_cache(now=now)
        self.store.write("arc.guess_aliases", payload)
        return payload

    def load_alias_cache(self) -> dict:
        payload = self.store.read_with_legacy(
            "arc.guess_aliases",
            {},
            lambda: self._load_legacy_json(self.cache_path, self.legacy_cache_path, {}),
        )
        return payload or self.sync_alias_cache()

    def _load_song_titles(self) -> list[dict[str, str | list[str]]]:
        return load_song_titles(self.chart_root / "songlist")

    def _build_base_aliases(self, title: str) -> list[str]:
        aliases = [title]
        acronym = "".join(re.findall(r"[A-Za-z0-9]+", title))
        if " " in title or "-" in title or "_" in title:
            short = "".join(part[0] for part in re.findall(r"[A-Za-z0-9]+", title) if part)
            if short and short.lower() != acronym.lower():
                aliases.append(short.lower())
        elif acronym and acronym.lower() != title.lower():
            aliases.append(acronym.lower())
        return aliases

    def _load_manual_aliases(self) -> dict[str, list[str]]:
        payload = self.store.read_with_legacy(
            "arc.guess_manual_aliases",
            {},
            lambda: self._load_legacy_json(self.manual_alias_path, self.legacy_manual_alias_path, {}),
        )
        songs = payload.get("songs", {})
        if not isinstance(songs, dict):
            return {}

        result: dict[str, list[str]] = {}
        for song_id, raw_aliases in songs.items():
            aliases = raw_aliases
            if isinstance(raw_aliases, dict):
                aliases = raw_aliases.get("aliases", [])
            if not isinstance(aliases, list):
                continue
            cleaned = [str(alias).strip() for alias in aliases if str(alias).strip()]
            if cleaned:
                result[str(song_id)] = cleaned
        return result

    def _append_aliases(self, aliases: list[str], candidates: list[str]) -> None:
        for candidate in candidates:
            alias = str(candidate).strip()
            if alias and alias not in aliases:
                aliases.append(alias)

    def _load_legacy_json(self, primary_path: Path, legacy_path: Path, default: dict) -> dict | None:
        for path in (primary_path, legacy_path):
            if path.exists():
                return read_json_file(path, default)
        return None


def load_song_titles(songlist_path: Path) -> list[dict[str, str | list[str]]]:
    payload = json.loads(songlist_path.read_text(encoding="utf-8"))
    songs = []
    for song in payload.get("songs", []):
        if song.get("deleted"):
            continue
        song_id = str(song.get("id", "")).strip()
        title_localized = song.get("title_localized", {})
        if not isinstance(title_localized, dict):
            title_localized = {}
        title = str(
            title_localized.get("en")
            or title_localized.get("zh-Hans")
            or title_localized.get("zh-Hant")
            or title_localized.get("ja")
            or next((value for value in title_localized.values() if value), "")
        ).strip()
        if not song_id or not title:
            continue
        localized_titles = [title]
        for value in title_localized.values():
            localized_title = str(value).strip()
            if localized_title and localized_title not in localized_titles:
                localized_titles.append(localized_title)
        songs.append({"id": song_id, "title": title, "localized_titles": localized_titles})
    return songs
