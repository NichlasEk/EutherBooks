from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from shutil import which
from typing import Any


class TtsError(RuntimeError):
    pass


class TtsBackend:
    name = "base"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError


class EspeakBackend(TtsBackend):
    name = "espeak"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, Any] | None = None,
    ) -> None:
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

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        binary = _piper_binary()
        if binary is None:
            raise TtsError(
                "Install Piper TTS, set EUTHERBOOKS_PIPER_BIN, or place the binary at tools/piper/piper."
            )
        if not voice:
            raise TtsError("Piper backend requires EUTHERBOOKS_TTS_VOICE to point to a model file.")
        model = _piper_model_path(voice, language)
        if not model.exists():
            raise TtsError(f"Piper model file does not exist: {model}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as input_file:
            input_file.write(text)
            input_file.flush()
            command = [str(binary), "--model", str(model), "--output_file", str(output_path)]
            command.extend(_piper_option_args(options or {}))
            subprocess.run(
                command,
                stdin=open(input_file.name, encoding="utf-8"),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )


def _piper_binary() -> Path | None:
    configured = os.environ.get("EUTHERBOOKS_PIPER_BIN")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path("tools/piper/piper").resolve(),
        Path("tools/piper/piper/piper").resolve(),
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and candidate.is_file():
            return candidate

    path_binary = which("piper")
    if path_binary:
        binary = Path(path_binary)
        try:
            help_output = subprocess.run(
                [str(binary), "--help"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=3,
            ).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return None
        if "--model" in help_output and "--output_file" in help_output:
            return binary
    return None


def _piper_model_path(voice: str, language: str) -> Path:
    configured = Path(voice).expanduser()
    if configured.exists() or configured.suffix == ".onnx" or configured.is_absolute():
        return configured
    local_model = Path("models/piper") / f"{voice}.onnx"
    if local_model.exists():
        return local_model

    normalized = voice.strip().lower().replace("-", "_")
    language_normalized = language.strip().lower().replace("-", "_")
    alias = normalized or language_normalized
    if alias in {"sv", "se", "sv_se", "sv_se_nst"} or language_normalized in {"sv", "sv_se"}:
        return Path(
            os.environ.get("EUTHERBOOKS_PIPER_VOICE_SV", "models/piper/sv_SE-nst-medium.onnx")
        ).expanduser()
    if alias in {"en", "en_us", "en_us_lessac"} or language_normalized in {"en", "en_us"}:
        return Path(
            os.environ.get("EUTHERBOOKS_PIPER_VOICE_EN", "models/piper/en_US-lessac-medium.onnx")
        ).expanduser()
    return configured


def _piper_option_args(options: dict[str, Any]) -> list[str]:
    args: list[str] = []
    option_map = {
        "length_scale": "--length_scale",
        "noise_scale": "--noise_scale",
        "noise_w": "--noise_w",
        "sentence_silence": "--sentence_silence",
    }
    for key, flag in option_map.items():
        value = options.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        args.extend([flag, f"{numeric:g}"])
    return args


def backend_from_name(name: str) -> TtsBackend:
    normalized = name.strip().lower()
    if normalized == "espeak":
        return EspeakBackend()
    if normalized == "piper":
        return PiperBackend()
    raise TtsError(f"Unknown TTS backend: {name}")
