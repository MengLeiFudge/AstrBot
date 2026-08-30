from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont

from ...runtime_storage import RuntimeJsonStore
from ...runtime_storage import infer_runtime_root_from_path
from ...runtime_storage import read_json_file


DIFFICULTY_LABELS = {
    0: "PST",
    1: "PRS",
    2: "FTR",
    3: "BYD",
    4: "ETR",
}


@dataclass(frozen=True, slots=True)
class ArcGuessCatalogEntry:
    song_id: str
    title: str
    aliases: list[str]


@dataclass(slots=True)
class ArcGuessQuestion:
    index: int
    song_id: str
    real_name: str
    aliases: list[str]
    is_solved: bool = False
    solved_by: str = ""


@dataclass(frozen=True, slots=True)
class ArcGuessMessage:
    text: str
    image_path: Path | None = None


@dataclass(slots=True)
class ArcGuessSession:
    started_at: str
    opened_letters: list[str]
    questions: list[ArcGuessQuestion]
    mode: str = "letters"
    art_song_id: str = ""
    art_real_name: str = ""
    art_aliases: list[str] | None = None
    art_jacket_path: str = ""
    opened_tiles: list[int] | None = None
    art_grid_size: int = 5


class ArcGuessService:
    def __init__(
        self,
        assets_root: Path,
        alias_cache_path: Path,
        state_path: Path,
        output_root: Path | None = None,
        timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        self.assets_root = Path(assets_root)
        self.chart_root = self.assets_root / "官谱"
        self.alias_cache_path = Path(alias_cache_path)
        self.state_path = Path(state_path)
        runtime_root = infer_runtime_root_from_path(self.state_path)
        self.output_root = Path(output_root) if output_root is not None else runtime_root / "cache" / "arc"
        self.store = RuntimeJsonStore(runtime_root)
        self.legacy_alias_cache_path = runtime_root / "data" / "arc" / self.alias_cache_path.name
        self.legacy_state_path = runtime_root / "data" / "arc" / self.state_path.name
        self.legacy_constants_path = runtime_root / "data" / "arc" / "constants.json"
        self.timeout = timeout
        self.sessions = self._load()

    def start_game(
        self,
        room_id: int,
        question_count: int,
        picker=None,
        now: datetime | None = None,
    ) -> str:
        current = self._coerce_now(now)
        existing = self.get_session(room_id)
        if existing is not None and not self._is_expired(existing, current):
            self._touch_session(existing, current)
            self._save()
            return "当前已经有一局 Arc 猜歌了，请先发送 ar。"
        expired_message = None
        if existing is not None and self._is_expired(existing, current):
            expired_message = self._expire_session(room_id, existing)

        entries = self._load_catalog_entries()
        if not entries:
            return "当前本地曲库为空，暂时不能开始 Arc 猜歌。"
        count = max(1, min(question_count, len(entries)))
        chooser = picker or (lambda items, size: random.sample(items, size))
        selected = chooser(entries, count)
        questions = [
            ArcGuessQuestion(
                index=index,
                song_id=entry.song_id,
                real_name=entry.title,
                aliases=list(entry.aliases),
            )
            for index, entry in enumerate(selected, start=1)
        ]
        self.sessions[str(room_id)] = ArcGuessSession(
            started_at=current.isoformat(),
            opened_letters=[],
            questions=questions,
        )
        self._save()
        text = "已开始 Arc 猜歌：\n" + self._render_panel(self.sessions[str(room_id)])
        if expired_message is not None:
            text = f"{expired_message.text}\n\n{text}"
        return text

    def start_art_game(
        self,
        room_id: int,
        grid_size: int | str | None = 5,
        picker=None,
        tile_picker=None,
        now: datetime | None = None,
    ) -> ArcGuessMessage:
        current = self._coerce_now(now)
        existing = self.get_session(room_id)
        if existing is not None and not self._is_expired(existing, current):
            self._touch_session(existing, current)
            self._save()
            return ArcGuessMessage("当前已经有一局 Arc 猜歌了，请先发送 ar。")
        expired_message = None
        if existing is not None and self._is_expired(existing, current):
            expired_message = self._expire_session(room_id, existing)

        entries = [entry for entry in self._load_catalog_entries() if self._find_jacket_path(entry.song_id)]
        if not entries:
            return ArcGuessMessage("当前本地曲库没有可用曲绘，暂时不能开始 Arc 曲绘猜歌。")
        chooser = picker or random.choice
        entry = chooser(entries)
        jacket_path = self._find_jacket_path(entry.song_id)
        if jacket_path is None:
            return ArcGuessMessage("选中的歌曲没有可用曲绘，请稍后重试。")

        session = ArcGuessSession(
            started_at=current.isoformat(),
            opened_letters=[],
            questions=[],
            mode="art",
            art_song_id=entry.song_id,
            art_real_name=entry.title,
            art_aliases=list(entry.aliases),
            art_jacket_path=str(jacket_path),
            opened_tiles=[],
            art_grid_size=self._normalize_grid_size(grid_size, jacket_path),
        )
        self.sessions[str(room_id)] = session
        message = self._open_next_art_tile(room_id, session, tile_picker, "已开始 Arc 曲绘猜歌。")
        if expired_message is not None:
            message.text = f"{expired_message.text}\n\n{message.text}"
        self._save()
        return message

    def start_or_open_art_tile(
        self,
        room_id: int,
        grid_size: int | str | None = None,
        picker=None,
        tile_picker=None,
        now: datetime | None = None,
    ) -> ArcGuessMessage:
        session = self.get_session(room_id)
        current = self._coerce_now(now)
        if session is None or self._is_expired(session, current):
            return self.start_art_game(room_id, grid_size or 5, picker, tile_picker, current)
        if session.mode == "art":
            if grid_size == "max":
                total_tiles = session.art_grid_size * session.art_grid_size
                tile_count = total_tiles - len(session.opened_tiles or [])
            else:
                tile_count = int(grid_size or 1)
            return self.open_art_tile(room_id, tile_picker, current, tile_count=tile_count)
        self._touch_session(session, current)
        self._save()
        return ArcGuessMessage("当前进行的是字母猜歌，不能补图。")

    def open_art_tile(
        self,
        room_id: int,
        tile_picker=None,
        now: datetime | None = None,
        tile_count: int = 1,
    ) -> ArcGuessMessage:
        current = self._coerce_now(now)
        session = self.get_session(room_id)
        if session is None:
            return ArcGuessMessage("当前没有进行中的 Arc 曲绘猜歌，发送 aa 开始一局。")
        if self._is_expired(session, current):
            return self._expire_session(room_id, session)
        if session.mode != "art":
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage("当前进行的是字母猜歌，不能补图。")
        total_tiles = session.art_grid_size * session.art_grid_size
        if len(session.opened_tiles or []) >= total_tiles:
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage(f"{total_tiles} 个格子已经全部开完，可以继续猜或发送 arcjx。")

        message = self._open_next_art_tile(room_id, session, tile_picker, None, tile_count)
        self._touch_session(session, current)
        self._save()
        return message

    def open_letter(
        self,
        room_id: int,
        letter: str,
        now: datetime | None = None,
    ) -> ArcGuessMessage:
        current = self._coerce_now(now)
        session = self.get_session(room_id)
        if session is None:
            return ArcGuessMessage("当前没有进行中的 Arc 猜歌，发送 arczm 开始一局。")
        if self._is_expired(session, current):
            return self._expire_session(room_id, session)
        if session.mode != "letters":
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage("当前进行的是曲绘猜歌，不能开字母。")

        normalized = letter.strip().lower()
        if len(normalized) != 1 or normalized.isspace():
            return ArcGuessMessage("开字符只支持单个非空格字符，例如：开*")
        if normalized in session.opened_letters:
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage(f"字符 {normalized} 已经开过了。\n" + self._render_panel(session))
        session.opened_letters.append(normalized)
        auto_solved = self._auto_solve_visible_questions(session)
        self._touch_session(session, current)
        self._save()
        text = f"已开字符：{normalized}\n" + self._render_panel(session)
        if auto_solved:
            text += "\n" + "\n".join(
                f"自动揭晓第 {question.index} 首：{question.real_name}" for question in auto_solved
            )
            if all(item.is_solved for item in session.questions):
                answer_image_path = self._render_letter_answer_image(room_id, session)
                self._clear_session(room_id)
                return ArcGuessMessage("游戏结束，答案如下：", answer_image_path)
            return ArcGuessMessage(text, self._find_jacket_path(auto_solved[0].song_id))
        return ArcGuessMessage(text)

    def guess(
        self,
        room_id: int,
        question_index: int,
        answer: str,
        player_name: str,
        now: datetime | None = None,
    ) -> ArcGuessMessage:
        current = self._coerce_now(now)
        session = self.get_session(room_id)
        if session is None:
            return ArcGuessMessage("当前没有进行中的 Arc 猜歌，发送 arczm 开始一局。")
        if self._is_expired(session, current):
            return self._expire_session(room_id, session)
        if session.mode != "letters":
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage("当前进行的是曲绘猜歌，请直接发送曲名作答。")

        question = next((item for item in session.questions if item.index == question_index), None)
        if question is None:
            return ArcGuessMessage(f"没有第 {question_index} 首题。")
        if question.is_solved:
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage(f"第 {question_index} 首已经被 {question.solved_by} 猜出。")

        if self._is_accepted_answer(answer, question.aliases):
            question.is_solved = True
            question.solved_by = player_name
            jacket_path = self._find_jacket_path(question.song_id)
            self._touch_session(session, current)
            self._save()
            if all(item.is_solved for item in session.questions):
                answer_image_path = self._render_letter_answer_image(room_id, session)
                self._clear_session(room_id)
                return ArcGuessMessage("游戏结束，答案如下：", answer_image_path)
            return ArcGuessMessage(
                f"答对了第 {question_index} 首：{question.real_name}\n" + self._render_panel(session),
                jacket_path,
            )

        self._touch_session(session, current)
        self._save()
        return ArcGuessMessage(f"不对，第 {question_index} 首还没猜出来。\n" + self._render_panel(session))

    def guess_art(
        self,
        room_id: int,
        answer: str,
        player_name: str,
        now: datetime | None = None,
    ) -> ArcGuessMessage:
        current = self._coerce_now(now)
        session = self.get_session(room_id)
        if session is None:
            return ArcGuessMessage("当前没有进行中的 Arc 曲绘猜歌，发送 aa 开始一局。")
        if self._is_expired(session, current):
            return self._expire_session(room_id, session)
        if session.mode != "art":
            self._touch_session(session, current)
            self._save()
            return ArcGuessMessage("当前进行的是字母猜歌，请使用“猜2 曲名”作答。")

        if self._is_accepted_answer(answer, session.art_aliases or []):
            title = session.art_real_name
            jacket_path = Path(session.art_jacket_path) if session.art_jacket_path else None
            self._clear_session(room_id)
            return ArcGuessMessage(f"{player_name} 答对了：{title}", jacket_path)
        self._touch_session(session, current)
        self._save()
        return ArcGuessMessage("不对，这首曲绘还没猜出来。")

    def reveal_answers(self, room_id: int) -> str | ArcGuessMessage:
        session = self.get_session(room_id)
        if session is None:
            return "当前没有进行中的 Arc 猜歌。"
        message = self._build_reveal_message(session, "游戏结束", room_id)
        self._clear_session(room_id)
        return message

    def collect_expired_sessions(self, now: datetime | None = None) -> list[tuple[int, ArcGuessMessage]]:
        current = self._coerce_now(now)
        expired: list[tuple[int, ArcGuessMessage]] = []
        for key, session in list(self.sessions.items()):
            if not self._is_expired(session, current):
                continue
            room_id = int(key)
            expired.append((room_id, self._expire_session(room_id, session)))
        return expired

    def _build_reveal_message(self, session: ArcGuessSession, prefix: str, room_id: int | None = None) -> str | ArcGuessMessage:
        if session.mode == "art":
            title = session.art_real_name
            jacket_path = Path(session.art_jacket_path) if session.art_jacket_path else None
            return ArcGuessMessage(f"{prefix}，答案是：{title}", jacket_path)
        lines = [f"{prefix}，答案如下："]
        return ArcGuessMessage(lines[0], self._render_letter_answer_image(room_id or 0, session))

    def _open_next_art_tile(
        self,
        room_id: int,
        session: ArcGuessSession,
        tile_picker,
        prefix: str | None,
        tile_count: int = 1,
    ) -> ArcGuessMessage:
        opened_tiles = session.opened_tiles or []
        grid_size = session.art_grid_size
        total_tiles = grid_size * grid_size
        choices = [tile for tile in range(1, total_tiles + 1) if tile not in opened_tiles]
        opened_count = min(max(1, tile_count), len(choices))
        if tile_picker is None:
            opened_tiles.extend(random.sample(choices, opened_count))
        else:
            for _ in range(opened_count):
                tile = tile_picker(choices)
                opened_tiles.append(tile)
                choices.remove(tile)
        session.opened_tiles = opened_tiles
        image_path = self._render_art_panel(room_id, session)
        if prefix is None:
            prefix = "补充了一块曲绘。" if opened_count == 1 else f"补充了 {opened_count} 块曲绘。"
        text = f"{prefix}\n已开放格子：{len(opened_tiles)}/{total_tiles}\n直接发送曲名作答，或发送 arcqh。"
        return ArcGuessMessage(text=text, image_path=image_path)

    def _render_art_panel(self, room_id: int, session: ArcGuessSession) -> Path:
        jacket_path = Path(session.art_jacket_path)
        grid_size = session.art_grid_size
        output = self.output_root / "guess_art_tiles" / str(room_id) / "panel.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(jacket_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            panel = Image.new("RGB", image.size, (88, 88, 88))
            for tile in session.opened_tiles or []:
                row = (tile - 1) // grid_size
                column = (tile - 1) % grid_size
                left = column * width // grid_size
                upper = row * height // grid_size
                right = (column + 1) * width // grid_size
                lower = (row + 1) * height // grid_size
                panel.paste(image.crop((left, upper, right, lower)), (left, upper))
            panel.save(output, format="PNG")
        return output

    def _find_jacket_path(self, song_id: str) -> Path | None:
        for directory in (self.chart_root / song_id, self.chart_root / f"dl_{song_id}"):
            for filename in ("base.jpg", "1080_base.jpg"):
                path = directory / filename
                if path.exists():
                    return path
        return None

    def _normalize_grid_size(self, grid_size: int | str | None, jacket_path: Path) -> int:
        max_grid_size = self._max_supported_grid_size(jacket_path)
        if grid_size == "max":
            return max_grid_size
        return max(1, min(int(grid_size or 5), max_grid_size))

    def _max_supported_grid_size(self, jacket_path: Path) -> int:
        with Image.open(jacket_path) as image:
            width, height = image.size
        return max(1, min(width, height))

    def _render_letter_answer_image(self, room_id: int, session: ArcGuessSession) -> Path:
        output = self.output_root / "guess_answer_panels" / str(room_id) / "answers.png"
        output.parent.mkdir(parents=True, exist_ok=True)

        row_height = 140
        jacket_size = 100
        width = 960
        height = max(row_height, row_height * len(session.questions))
        canvas = Image.new("RGB", (width, height), (246, 246, 246))
        draw = ImageDraw.Draw(canvas)
        title_font = self._load_font(28, bold=True)
        meta_font = self._load_font(22)
        small_font = self._load_font(18)

        for row_index, question in enumerate(session.questions):
            top = row_index * row_height
            draw.rectangle((0, top, width, top + row_height - 1), fill=(255, 255, 255))
            if row_index:
                draw.line((0, top, width, top), fill=(224, 224, 224), width=1)

            jacket_path = self._find_jacket_path(question.song_id)
            if jacket_path is not None:
                with Image.open(jacket_path) as source:
                    jacket = source.convert("RGB").resize((jacket_size, jacket_size), Image.Resampling.NEAREST)
                canvas.paste(jacket, (20, top + 20))
            else:
                draw.rectangle((20, top + 20, 20 + jacket_size, top + 20 + jacket_size), fill=(210, 210, 210))

            text_left = 140
            draw.text((text_left, top + 18), f"{question.index}. {question.real_name}", fill=(28, 28, 28), font=title_font)
            if question.solved_by:
                draw.text((text_left, top + 56), f"被 {question.solved_by} 猜出", fill=(78, 78, 78), font=small_font)
            draw.text(
                (text_left, top + 88),
                self._build_difficulty_summary(question.song_id),
                fill=(42, 42, 42),
                font=meta_font,
            )

        canvas.save(output, format="PNG")
        return output

    def _build_difficulty_summary(self, song_id: str) -> str:
        song = self._load_song_payload_by_id().get(song_id, {})
        constants = self._load_constants_payload().get(song_id, {}).get("constants", {})
        parts: list[str] = []
        for difficulty in song.get("difficulties", []):
            rating_class = int(difficulty.get("ratingClass", -1))
            label = DIFFICULTY_LABELS.get(rating_class)
            if label is None:
                continue
            constant = constants.get(str(rating_class))
            if constant is None:
                constant = self._fallback_constant_value(difficulty)
            parts.append(f"{label} {float(constant):.1f}")
        return " / ".join(parts) if parts else "暂无定数"

    def _fallback_constant_value(self, difficulty: dict) -> float:
        rating = float(difficulty.get("rating", 0))
        if rating >= 20:
            return rating / 10
        return rating + (0.7 if difficulty.get("ratingPlus") else 0)

    def _load_song_payload_by_id(self) -> dict[str, dict]:
        payload = json.loads((self.chart_root / "songlist").read_text(encoding="utf-8"))
        return {
            str(song.get("id", "")).strip(): song
            for song in payload.get("songs", [])
            if str(song.get("id", "")).strip()
        }

    def _load_constants_payload(self) -> dict[str, dict]:
        constants_path = self.alias_cache_path.with_name("constants.json")
        payload = self.store.read_with_legacy(
            "arc.constants",
            {"updated_at": "", "songs": {}},
            lambda: self._load_legacy_json(
                constants_path,
                self.legacy_constants_path,
                {"updated_at": "", "songs": {}},
            ),
        )
        return dict(payload.get("songs", {}))

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.ImageFont:
        candidates = (
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/mnt/c/Windows/Fonts/msyhbd.ttc" if bold else "/mnt/c/Windows/Fonts/msyh.ttc",
            "/mnt/c/Windows/Fonts/simhei.ttf",
        )
        for candidate in candidates:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default()

    def get_session(self, room_id: int) -> ArcGuessSession | None:
        return self.sessions.get(str(room_id))

    def _render_panel(self, session: ArcGuessSession) -> str:
        lines = []
        for question in session.questions:
            if question.is_solved:
                lines.append(
                    f"{question.index}. ✅ {question.real_name}（被 {question.solved_by} 猜出）"
                )
                continue
            lines.append(
                f"{question.index}. {self._mask_answer(question.real_name, session.opened_letters)}"
            )
        opened = "无" if not session.opened_letters else " ".join(session.opened_letters)
        lines.append(f"已开字符：{opened}")
        return "\n".join(lines)

    def _mask_answer(self, answer: str, opened_letters: list[str]) -> str:
        visible = set(opened_letters)
        chars = []
        for char in answer:
            if char == " ":
                chars.append(char)
            elif char.lower() in visible:
                chars.append(char)
            else:
                chars.append("*")
        return "".join(chars)

    def _auto_solve_visible_questions(self, session: ArcGuessSession) -> list[ArcGuessQuestion]:
        solved: list[ArcGuessQuestion] = []
        for question in session.questions:
            if question.is_solved:
                continue
            if "*" in self._mask_answer(question.real_name, session.opened_letters):
                continue
            question.is_solved = True
            question.solved_by = "开字符"
            solved.append(question)
        return solved

    def _load_catalog_entries(self) -> list[ArcGuessCatalogEntry]:
        alias_payload = self._load_alias_payload()
        songs = json.loads((self.chart_root / "songlist").read_text(encoding="utf-8")).get("songs", [])
        entries: list[ArcGuessCatalogEntry] = []
        for song in songs:
            if song.get("deleted"):
                continue
            song_id = str(song.get("id", "")).strip()
            title = str(song.get("title_localized", {}).get("en", "")).strip()
            if not song_id or not title:
                continue
            alias_entry = alias_payload.get(song_id, {})
            aliases = list(alias_entry.get("aliases", [title]))
            if title not in aliases:
                aliases.insert(0, title)
            entries.append(ArcGuessCatalogEntry(song_id=song_id, title=title, aliases=aliases))
        return entries

    def _load_alias_payload(self) -> dict[str, dict]:
        payload = self.store.read_with_legacy(
            "arc.guess_aliases",
            {},
            lambda: self._load_legacy_json(self.alias_cache_path, self.legacy_alias_cache_path, {}),
        )
        return dict(payload.get("songs", {}))

    def _is_expired(self, session: ArcGuessSession, now: datetime) -> bool:
        return now - datetime.fromisoformat(session.started_at) > self.timeout

    def _touch_session(self, session: ArcGuessSession, now: datetime) -> None:
        session.started_at = now.isoformat()

    def _expire_session(self, room_id: int, session: ArcGuessSession) -> ArcGuessMessage:
        message = self._build_reveal_message(session, "这一局 Arc 猜歌已经超时", room_id)
        self._clear_session(room_id)
        if isinstance(message, ArcGuessMessage):
            return message
        return ArcGuessMessage(message)

    def _clear_session(self, room_id: int) -> None:
        self.sessions.pop(str(room_id), None)
        self._save()

    def _normalize_answer(self, text: str) -> str:
        return "".join(char.lower() for char in text if char.isalnum())

    def _is_accepted_answer(self, answer: str, aliases: list[str]) -> bool:
        return self.is_plausible_answer(answer, aliases)

    def is_plausible_answer(self, answer: str, aliases: list[str]) -> bool:
        normalized_answer = self._normalize_answer(answer)
        if not normalized_answer:
            return False

        for alias in aliases:
            normalized_alias = self._normalize_answer(alias)
            if not normalized_alias:
                continue
            if normalized_answer == normalized_alias:
                return True
            if self._is_safe_partial_match(normalized_answer, normalized_alias):
                return True
            if self._is_safe_fuzzy_match(normalized_answer, normalized_alias):
                return True
        return False

    def _is_safe_partial_match(self, answer: str, alias: str) -> bool:
        if answer not in alias:
            return False
        return len(answer) / len(alias) >= 0.5

    def _is_safe_fuzzy_match(self, answer: str, alias: str) -> bool:
        # 高置信度才接受，覆盖 dancin/dancing、felis/fellis 这类小拼写差异。
        if min(len(answer), len(alias)) < 5:
            return False
        return SequenceMatcher(None, answer, alias).ratio() >= 0.9

    def _should_hide(self, char: str) -> bool:
        return char != " "

    def _coerce_now(self, now: datetime | None) -> datetime:
        return now or datetime.now()

    def _load(self) -> dict[str, ArcGuessSession]:
        raw = self.store.read_with_legacy(
            "arc.guess_sessions",
            {},
            lambda: self._load_legacy_json(self.state_path, self.legacy_state_path, {}),
        )
        return {
            key: ArcGuessSession(
                started_at=value["started_at"],
                opened_letters=list(value.get("opened_letters", [])),
                questions=[
                    ArcGuessQuestion(
                        index=int(question["index"]),
                        song_id=question["song_id"],
                        real_name=question["real_name"],
                        aliases=list(question.get("aliases", [])),
                        is_solved=bool(question.get("is_solved", False)),
                        solved_by=str(question.get("solved_by", "")),
                    )
                    for question in value.get("questions", [])
                ],
                mode=str(value.get("mode", "letters")),
                art_song_id=str(value.get("art_song_id", "")),
                art_real_name=str(value.get("art_real_name", "")),
                art_aliases=list(value.get("art_aliases") or []),
                art_jacket_path=str(value.get("art_jacket_path", "")),
                opened_tiles=list(value.get("opened_tiles") or []),
                art_grid_size=int(value.get("art_grid_size", 5)),
            )
            for key, value in raw.items()
        }

    def _save(self) -> None:
        payload = {key: asdict(value) for key, value in self.sessions.items()}
        self.store.write("arc.guess_sessions", payload)

    def _load_legacy_json(self, primary_path: Path, legacy_path: Path, default: dict) -> dict | None:
        for path in (primary_path, legacy_path):
            if path.exists():
                return read_json_file(path, default)
        return None
