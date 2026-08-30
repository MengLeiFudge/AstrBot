from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable


@dataclass(slots=True)
class ApkDownloadResult:
    version: str
    path: Path
    output: str


class ArcaeaRecordApkDownloader:
    def __init__(
        self,
        project_root: Path,
        target_dir: Path,
        maven_command: str = "",
        java_home: str = "",
    ) -> None:
        self.project_root = Path(project_root)
        self.target_dir = Path(target_dir)
        self.maven_command = maven_command
        self.java_home = java_home

    def download_latest_apk(
        self,
        version: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ApkDownloadResult:
        if not self.project_root.exists():
            raise RuntimeError(f"arcaeaRecord 项目目录不存在：{self.project_root}")

        env = self._build_env()
        self._run(
            [self._resolve_maven_command(), "-q", "-DskipTests", "compile"],
            timeout=180,
            env=env,
        )
        output = self._run_streaming(
            [
                self._resolve_java_command(),
                "-cp",
                str(self.project_root / "target" / "classes"),
                "arc.record.Main",
                "6",
                str(self.target_dir),
            ],
            timeout=900,
            env=env,
            progress_callback=progress_callback,
        )
        downloaded_path = self._parse_downloaded_path(output)
        return ApkDownloadResult(version=version, path=downloaded_path, output=output)

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        java_home = self.java_home or env.get("JAVA_HOME", "")
        if java_home:
            env["JAVA_HOME"] = java_home
            java_bin = str(Path(java_home) / "bin")
            env["Path" if os.name == "nt" else "PATH"] = (
                java_bin + os.pathsep + env.get("Path" if os.name == "nt" else "PATH", "")
            )
        return env

    def _resolve_maven_command(self) -> str:
        if self.maven_command:
            return self.maven_command
        return shutil.which("mvn.cmd") or shutil.which("mvn") or "mvn"

    def _resolve_java_command(self) -> str:
        java_home = self.java_home or os.environ.get("JAVA_HOME", "")
        if java_home:
            candidate = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
            return str(candidate)
        return shutil.which("java") or "java"

    def _run(self, command: list[str], timeout: int, env: dict[str, str]) -> str:
        process = subprocess.run(
            command,
            cwd=self.project_root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if process.returncode != 0:
            output = process.stdout.strip()
            raise RuntimeError(
                "arcaeaRecord 执行失败："
                + " ".join(command)
                + ("\n" + output[-2000:] if output else "")
            )
        return process.stdout

    def _run_streaming(
        self,
        command: list[str],
        timeout: int,
        env: dict[str, str],
        progress_callback: Callable[[str], None] | None,
    ) -> str:
        process = subprocess.Popen(
            command,
            cwd=self.project_root,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output_lines: list[str] = []
        assert process.stdout is not None
        try:
            for line in process.stdout:
                output_lines.append(line)
                progress_message = self._parse_progress_message(line)
                if progress_message is not None and progress_callback is not None:
                    progress_callback(progress_message)
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError("arcaeaRecord 下载超时")
        if return_code != 0:
            output = "".join(output_lines).strip()
            raise RuntimeError(
                "arcaeaRecord 执行失败："
                + " ".join(command)
                + ("\n" + output[-2000:] if output else "")
            )
        return "".join(output_lines)

    @staticmethod
    def _parse_progress_message(line: str) -> str | None:
        line = line.strip()
        if not line.startswith("APK_PROGRESS "):
            return None
        parts = line.split()
        if len(parts) != 4:
            return None
        percent = parts[1]
        downloaded = ArcaeaRecordApkDownloader._format_bytes(parts[2])
        total = ArcaeaRecordApkDownloader._format_bytes(parts[3])
        return f"{percent}%（{downloaded} / {total}）"

    @staticmethod
    def _format_bytes(raw_value: str) -> str:
        try:
            value = int(raw_value)
        except ValueError:
            return raw_value
        if value < 0:
            return "未知大小"
        mib = value / 1024 / 1024
        if mib >= 1024:
            return f"{mib / 1024:.2f} GiB"
        return f"{mib:.1f} MiB"

    @staticmethod
    def _parse_downloaded_path(output: str) -> Path:
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("APK_DOWNLOADED "):
                return Path(line.removeprefix("APK_DOWNLOADED ").strip())
        raise RuntimeError("arcaeaRecord 未输出 APK_DOWNLOADED 路径")
