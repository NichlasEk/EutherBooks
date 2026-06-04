from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which


class TtsError(RuntimeError):
    pass


class TtsBackend:
    name = "base"

    def synthesize(self, text: str, output_path: Path, language: str, voice: str) -> None:
        raise NotImplementedError


class EspeakBackend(TtsBackend):
    name = "espeak"

    def synthesize(self, text: str, output_path: Path, language: str, voice: str) -> None:
        binary = which("espeak-ng") or which("espeak")
        if binary is None:
            raise TtsError("Install espeak-ng or choose another TTS backend.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [binary, "-v", voice or language, "-w", str(output_path), text],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


class PiperBackend(TtsBackend):
    name = "piper"

    def synthesize(self, text: str, output_path: Path, language: str, voice: str) -> None:
        binary = which("piper")
        if binary is None:
            raise TtsError("Install piper or choose another TTS backend.")
        model = voice
        if not model:
            raise TtsError("Piper backend requires EUTHERBOOKS_TTS_VOICE to point to a model file.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as input_file:
            input_file.write(text)
            input_file.flush()
            subprocess.run(
                [binary, "--model", model, "--output_file", str(output_path)],
                stdin=open(input_file.name, encoding="utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )


def backend_from_name(name: str) -> TtsBackend:
    normalized = name.strip().lower()
    if normalized == "espeak":
        return EspeakBackend()
    if normalized == "piper":
        return PiperBackend()
    raise TtsError(f"Unknown TTS backend: {name}")

