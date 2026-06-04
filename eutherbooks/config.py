from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path_from_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    library_dir: Path
    data_dir: Path
    audio_dir: Path
    cache_dir: Path
    default_language: str = "sv"
    tts_backend: str = "espeak"
    tts_voice: str = "sv"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = _path_from_env("EUTHERBOOKS_DATA_DIR", "data")
        return cls(
            library_dir=_path_from_env("EUTHERBOOKS_LIBRARY_DIR", "library"),
            data_dir=data_dir,
            audio_dir=_path_from_env("EUTHERBOOKS_AUDIO_DIR", str(data_dir / "audio")),
            cache_dir=_path_from_env("EUTHERBOOKS_CACHE_DIR", str(data_dir / "cache")),
            default_language=os.environ.get("EUTHERBOOKS_DEFAULT_LANGUAGE", "sv"),
            tts_backend=os.environ.get("EUTHERBOOKS_TTS_BACKEND", "espeak"),
            tts_voice=os.environ.get("EUTHERBOOKS_TTS_VOICE", "sv"),
        )

    def ensure_dirs(self) -> None:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

