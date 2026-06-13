from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
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
        temp_output = _temporary_output_path(output_path)
        try:
            subprocess.run(
                [binary, "-v", voice or language, "-w", str(temp_output), text],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            os.replace(temp_output, output_path)
        finally:
            temp_output.unlink(missing_ok=True)


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
        temp_output = _temporary_output_path(output_path)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as input_file:
            try:
                input_file.write(text)
                input_file.flush()
                command = [str(binary), "--model", str(model), "--output_file", str(temp_output)]
                command.extend(_piper_option_args(options or {}))
                subprocess.run(
                    command,
                    stdin=open(input_file.name, encoding="utf-8"),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                os.replace(temp_output, output_path)
            finally:
                temp_output.unlink(missing_ok=True)


class EutherLinkBackend(TtsBackend):
    name = "eutherlink"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        base_url = os.environ.get("EUTHERBOOKS_EUTHERLINK_URL", "http://192.168.32.88:8765").rstrip("/")
        timeout = float(os.environ.get("EUTHERBOOKS_EUTHERLINK_TIMEOUT", "15"))
        poll_interval = float(os.environ.get("EUTHERBOOKS_EUTHERLINK_POLL_INTERVAL", "1.0"))
        voice_instruction = _eutherlink_voice_instruction(voice)
        payload: dict[str, Any] = {
            "text": text,
            "voice_instruction": voice_instruction,
            "language": language,
            "output_format": "wav",
            "cfg_value": float((options or {}).get("cfg_value") or os.environ.get("EUTHERBOOKS_EUTHERLINK_CFG_VALUE", "2.0")),
            "inference_timesteps": int((options or {}).get("inference_timesteps") or os.environ.get("EUTHERBOOKS_EUTHERLINK_INFERENCE_TIMESTEPS", "10")),
            "max_chunk_chars": int((options or {}).get("max_chunk_chars") or os.environ.get("EUTHERBOOKS_EUTHERLINK_MAX_CHUNK_CHARS", "700")),
        }
        reference_path = _valid_voice_reference_path((options or {}).get("voice_reference_path"))
        prompt_text = _valid_voice_prompt_text((options or {}).get("voice_prompt_text"))
        if voice in {"own-sv", "own-en"} and reference_path:
            sample = Path(reference_path).read_bytes()
            sample_base64 = base64.b64encode(sample).decode("ascii")
            payload["prompt_wav_base64"] = sample_base64
            payload["reference_wav_base64"] = sample_base64
            if prompt_text:
                payload["prompt_text"] = prompt_text

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = _temporary_output_path(output_path)
        try:
            job = _request_json(f"{base_url}/v1/tts/jobs", payload, timeout)
            status_url = _absolute_worker_url(base_url, str(job["status_url"]))

            deadline = time.monotonic() + float(os.environ.get("EUTHERBOOKS_EUTHERLINK_JOB_TIMEOUT", "1800"))
            status = job
            while status.get("status") not in {"done", "failed"}:
                if time.monotonic() > deadline:
                    raise TtsError("EutherLink TTS job timed out.")
                time.sleep(poll_interval)
                status = _request_json(status_url, None, timeout)

            if status.get("status") != "done":
                raise TtsError(str(status.get("error") or status.get("message") or "EutherLink TTS job failed."))

            audio_url = _absolute_worker_url(base_url, str(status.get("audio_url") or job["audio_url"]))
            _download_file(audio_url, temp_output, timeout)
            os.replace(temp_output, output_path)
        finally:
            temp_output.unlink(missing_ok=True)


def _valid_voice_reference_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 600 or not value.endswith(".wav"):
        return ""
    try:
        path = Path(value).expanduser().resolve()
    except OSError:
        return ""
    root = Path(os.environ.get("EUTHERBOOKS_VOICE_REFERENCE_ROOT", "/home/nichlas/EutherOxide/.euther-host/user-data")).resolve()
    if root not in path.parents or not path.is_file():
        return ""
    return str(path)


def _valid_voice_prompt_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip()[:500] if ch == "\t" or ord(ch) >= 32)

def _temporary_output_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")


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
    if normalized in {"eutherlink", "vox", "voxcpm", "voxcpm2"}:
        return EutherLinkBackend()
    raise TtsError(f"Unknown TTS backend: {name}")


def _eutherlink_voice_instruction(voice: str) -> str:
    base = "Use the exact same speaker identity, timbre, accent, age, and performance style for every paragraph and every generated chunk. Do not switch voices between sentences, paragraphs, or chapter parts."
    configured = os.environ.get(
        "EUTHERBOOKS_EUTHERLINK_VOICE_INSTRUCTION",
        os.environ.get(
            "EUTHERBOOKS_TTS_VOICE",
            "A warm, clear Swedish audiobook narrator with calm natural pacing.",
        ),
    )
    value = voice.strip()
    normalized = value.lower().replace("-", "_")
    presets = {
        "sv": "A warm, clear Swedish audiobook narrator with calm natural pacing.",
        "se": "A warm, clear Swedish audiobook narrator with calm natural pacing.",
        "sv_female": "A warm adult female Swedish audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
        "female": "A warm adult female Swedish audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
        "sv_female_warm": "A warm adult female Swedish audiobook narrator, close and friendly, with clear pronunciation and relaxed pacing.",
        "sv_female_clear": "A precise adult female Swedish narrator with bright clarity, careful consonants, and steady audiobook pacing.",
        "sv_female_soft": "A soft adult female Swedish bedtime storyteller with gentle tone, low intensity, and smooth phrasing.",
        "sv_female_deep": "A lower-pitched adult female Swedish narrator with rich timbre, calm confidence, and measured pacing.",
        "sv_female_elder": "An older female Swedish storyteller with warm character, lived-in tone, clear diction, and unhurried pacing.",
        "sv_male": "A warm adult male Swedish audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
        "male": "A warm adult male Swedish audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
        "sv_male_warm": "A warm adult male Swedish audiobook narrator, close and friendly, with clear pronunciation and relaxed pacing.",
        "sv_male_clear": "A precise adult male Swedish narrator with clean diction, crisp consonants, and steady audiobook pacing.",
        "sv_male_deep": "A deep adult male Swedish narrator with resonant timbre, calm authority, and slow measured pacing.",
        "sv_male_soft": "A soft adult male Swedish storyteller with gentle tone, low intensity, and smooth phrasing.",
        "sv_male_elder": "An older male Swedish storyteller with warm character, weathered timbre, clear diction, and unhurried pacing.",
        "sv_neutral": "A calm neutral Swedish audiobook narrator with clear pronunciation and steady natural pacing.",
        "neutral": "A calm neutral Swedish audiobook narrator with clear pronunciation and steady natural pacing.",
        "sv_neutral_calm": "A calm neutral Swedish audiobook narrator with balanced tone, clean pronunciation, and steady pacing.",
        "sv_neutral_news": "A crisp Swedish documentary narrator with neutral delivery, high intelligibility, and controlled pacing.",
        "sv_neutral_theatre": "An expressive Swedish theatre narrator with controlled drama, clear diction, and consistent audiobook pacing.",
        "sv_whisper": "A quiet Swedish bedtime narrator with intimate near-whisper softness while staying clearly understandable.",
        "sv_character_bright": "A bright lively Swedish character narrator with energetic warmth, clear diction, and consistent playful tone.",
        "sv_character_gritty": "A gritty Swedish character narrator with rougher texture, lower intensity, clear diction, and consistent tone.",
        "en_female_warm": "A warm adult female English audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
        "en_male_warm": "A warm adult male English audiobook narrator with clear pronunciation, calm pacing, and natural emotional nuance.",
    }
    if normalized in presets:
        return f"{presets[normalized]} {base}"
    if not value or normalized in {"sv_se", "sv_se_nst", "en", "en_us", "en_us_lessac", "custom"}:
        return f"{configured} {base}"
    if value.endswith(".onnx") or "/" in value:
        return f"{configured} {base}"
    return f"{value} {base}"


def _request_json(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise TtsError(f"EutherLink request failed: {exc}") from exc


def _download_file(url: str, output_path: Path, timeout: float) -> None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            output_path.write_bytes(response.read())
    except urllib.error.URLError as exc:
        raise TtsError(f"EutherLink audio download failed: {exc}") from exc


def _absolute_worker_url(base_url: str, value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"{base_url}/{value.lstrip('/')}"
