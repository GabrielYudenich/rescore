from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tool:
    name: str
    path: str | None
    version: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _first_existing(candidates: list[str | Path | None]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
    return None


def find_audiveris(project_root: Path) -> Path | None:
    return _first_existing(
        [
            os.environ.get("RESCORE_AUDIVERIS"),
            shutil.which("Audiveris"),
            shutil.which("audiveris"),
            project_root / "tools" / "Audiveris" / "Audiveris" / "Audiveris.exe",
            Path("C:/Program Files/Audiveris/Audiveris.exe"),
        ]
    )


def find_musescore(project_root: Path) -> Path | None:
    del project_root
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates: list[str | Path | None] = [
        os.environ.get("RESCORE_MUSESCORE"),
        shutil.which("MuseScore4"),
        shutil.which("mscore"),
        shutil.which("musescore"),
        Path("C:/Program Files/MuseScore 4/bin/MuseScore4.exe"),
    ]
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "MuseScore 4" / "bin" / "MuseScore4.exe")
    return _first_existing(candidates)


def _version(path: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            [str(path), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"erro: {exc}"
    text = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return text[:4000] or f"código de saída {result.returncode}"


def doctor(project_root: Path) -> dict:
    audiveris = find_audiveris(project_root)
    musescore = find_musescore(project_root)
    return {
        "audiveris": Tool(
            "Audiveris",
            str(audiveris) if audiveris else None,
            _version(audiveris, ["-batch", "-version"]) if audiveris else None,
        ).to_dict(),
        "musescore": Tool(
            "MuseScore",
            str(musescore) if musescore else None,
            _version(musescore, ["--version"]) if musescore else None,
        ).to_dict(),
    }
