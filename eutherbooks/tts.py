from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from shutil import which
from typing import Any, Callable


LOGGER = logging.getLogger("eutherbooks.tts")


class TtsError(RuntimeError):
    pass


ProgressCallback = Callable[[dict[str, Any]], None]


class TtsBackend:
    name = "base"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
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
        progress_callback: ProgressCallback | None = None,
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
        progress_callback: ProgressCallback | None = None,
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
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        base_url = os.environ.get("EUTHERBOOKS_EUTHERLINK_URL", "http://192.168.32.88:8765").rstrip("/")
        timeout = float(os.environ.get("EUTHERBOOKS_EUTHERLINK_TIMEOUT", "15"))
        poll_interval = float(os.environ.get("EUTHERBOOKS_EUTHERLINK_POLL_INTERVAL", "1.0"))
        model_backend = _eutherlink_model_backend(voice, (options or {}).get("model_backend"))
        voice_id = _eutherlink_voice_id(voice)
        voice_instruction = _eutherlink_voice_instruction(voice_id)
        payload: dict[str, Any] = {
            "text": text,
            "voice_instruction": voice_instruction,
            "language": language,
            "output_format": "wav",
            "model_backend": model_backend,
            "cfg_value": float((options or {}).get("cfg_value") or os.environ.get("EUTHERBOOKS_EUTHERLINK_CFG_VALUE", "2.0")),
            "inference_timesteps": _clamped_int(
                (options or {}).get("inference_timesteps")
                or os.environ.get("EUTHERBOOKS_EUTHERLINK_INFERENCE_TIMESTEPS", "10"),
                10,
                50,
                10,
            ),
            "max_chunk_chars": int((options or {}).get("max_chunk_chars") or os.environ.get("EUTHERBOOKS_EUTHERLINK_MAX_CHUNK_CHARS", "700")),
        }
        if _needs_dots_reference(model_backend):
            payload.update(
                {
                    "dots_template_name": _dots_template_name((options or {}).get("dots_template_name")),
                    "dots_ode_method": _dots_ode_method((options or {}).get("dots_ode_method")),
                    "dots_num_steps": _clamped_int(
                        (options or {}).get("dots_num_steps")
                        or os.environ.get("EUTHERBOOKS_DOTS_NUM_STEPS", "4"),
                        1,
                        50,
                        4,
                    ),
                    "dots_guidance_scale": _clamped_float((options or {}).get("dots_guidance_scale"), 0.0, 5.0, 1.2),
                    "dots_speaker_scale": _clamped_float((options or {}).get("dots_speaker_scale"), 0.0, 5.0, 1.5),
                    "dots_max_generate_length": _clamped_int((options or {}).get("dots_max_generate_length"), 128, 4096, 500),
                }
            )
        seed = (options or {}).get("seed")
        explicit_seed = _positive_seed(seed)
        preset_seed = _eutherlink_stable_preset_seed(voice_id)
        if explicit_seed is not None:
            payload["seed"] = explicit_seed
        elif preset_seed is not None:
            payload["seed"] = preset_seed
        reference_path = _valid_voice_reference_path((options or {}).get("voice_reference_path"))
        prompt_text = _valid_voice_prompt_text((options or {}).get("voice_prompt_text"))
        if voice_id in {"own-sv", "own-en"}:
            reference_path = _own_voice_reference_path(voice_id, reference_path)
            prompt_text = _own_voice_prompt_text(voice_id, prompt_text)
        elif _needs_dots_reference(model_backend) and preset_seed is not None and not reference_path:
            preset_reference = _dots_preset_reference_path(
                base_url=base_url,
                timeout=timeout,
                poll_interval=poll_interval,
                model_backend=model_backend,
                voice_id=voice_id,
                language=language,
                voice_instruction=voice_instruction,
                seed=explicit_seed or preset_seed,
                template_name=payload.get("dots_template_name"),
                ode_method=payload.get("dots_ode_method"),
                num_steps=payload.get("dots_num_steps"),
                guidance_scale=payload.get("dots_guidance_scale"),
                speaker_scale=payload.get("dots_speaker_scale"),
                max_generate_length=payload.get("dots_max_generate_length"),
            )
            reference_path = str(preset_reference)
            prompt_text = _dots_preset_prompt_text(voice_id, language)
        sample_sha = ""
        sample_seed: int | None = None
        sample_size = 0
        if (voice_id in {"own-sv", "own-en"} or (_needs_dots_reference(model_backend) and prompt_text)) and reference_path:
            sample_path = Path(reference_path)
            sample = sample_path.read_bytes()
            sample_sha = _short_sha256(sample)
            sample_seed = _stable_voice_seed(sample)
            sample_size = len(sample)
            if voice_id in {"own-sv", "own-en"} and explicit_seed is None:
                payload["seed"] = sample_seed
            sample_base64 = base64.b64encode(sample).decode("ascii")
            payload["reference_wav_base64"] = sample_base64
            if prompt_text and (_needs_dots_reference(model_backend) or _use_eutherlink_prompt_transcript(prompt_text)):
                payload["prompt_wav_base64"] = sample_base64
                payload["prompt_text"] = prompt_text
        if _needs_dots_reference(model_backend) and voice_id in {"own-sv", "own-en"} and (
            "prompt_wav_base64" not in payload or not payload.get("prompt_text")
        ):
            raise TtsError(f"{model_backend} own voice requires a reference WAV and matching prompt text.")

        LOGGER.warning(
            "TTS_TRACE eutherbooks_submit voice=%s model_backend=%s lang=%s output=%s text_len=%s text_sha=%s seed_payload=%s seed_option=%s seed_source=%s sample_seed=%s reference_valid=%s reference_path=%s sample_size=%s sample_sha=%s prompt_text_len=%s prompt_text_sha=%s has_prompt_wav=%s has_reference_wav=%s cfg=%.3f steps=%s dots_guidance=%s dots_speaker=%s dots_steps=%s dots_max_len=%s max_chunk_chars=%s",
            voice,
            model_backend,
            language,
            output_path,
            len(text),
            _short_sha256(text.encode("utf-8")),
            payload.get("seed"),
            (options or {}).get("seed"),
            "explicit" if explicit_seed is not None else ("sample" if sample_seed is not None else ("preset" if preset_seed is not None else "none")),
            sample_seed,
            bool(reference_path),
            reference_path,
            sample_size,
            sample_sha,
            len(prompt_text),
            _short_sha256(prompt_text.encode("utf-8")),
            "prompt_wav_base64" in payload,
            "reference_wav_base64" in payload,
            float(payload["cfg_value"]),
            payload["inference_timesteps"],
            payload.get("dots_guidance_scale"),
            payload.get("dots_speaker_scale"),
            payload.get("dots_num_steps"),
            payload.get("dots_max_generate_length"),
            payload["max_chunk_chars"],
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = _temporary_output_path(output_path)
        length_scale = _eutherlink_length_scale((options or {}).get("length_scale"))
        downloaded_partials: dict[str, Path] = {}
        synth_started = time.perf_counter()
        poll_count = 0
        first_partial_sec: float | None = None
        worker_job_id: str | None = None

        def publish_partials(status_payload: dict[str, Any]) -> None:
            nonlocal first_partial_sec
            changed = False
            for value in status_payload.get("partial_audio_urls") or []:
                partial_url = _absolute_worker_url(base_url, str(value))
                if partial_url in downloaded_partials:
                    continue
                partial_path = output_path.with_name(f"{output_path.stem}.stream-{len(downloaded_partials) + 1:03d}.wav")
                temp_partial = _temporary_output_path(partial_path)
                try:
                    download_started = time.perf_counter()
                    _download_file(partial_url, temp_partial, timeout)
                    partial_download_sec = time.perf_counter() - download_started
                    if abs(length_scale - 1.0) > 0.001:
                        tempo_started = time.perf_counter()
                        _apply_eutherlink_length_scale(temp_partial, length_scale)
                        partial_tempo_sec = time.perf_counter() - tempo_started
                    else:
                        partial_tempo_sec = 0.0
                    os.replace(temp_partial, partial_path)
                finally:
                    temp_partial.unlink(missing_ok=True)
                downloaded_partials[partial_url] = partial_path
                if first_partial_sec is None:
                    first_partial_sec = time.perf_counter() - synth_started
                changed = True
                LOGGER.warning(
                    "TTS_TRACE eutherbooks_partial_download output=%s worker_job=%s partial=%s bytes=%s download_sec=%.3f tempo_sec=%.3f since_submit_sec=%.3f",
                    output_path,
                    status_payload.get("id") or job.get("id"),
                    partial_path,
                    partial_path.stat().st_size if partial_path.exists() else 0,
                    partial_download_sec,
                    partial_tempo_sec,
                    time.perf_counter() - synth_started,
                )
            if progress_callback is not None:
                update = dict(status_payload)
                update["partial_audio_paths"] = [str(path) for path in downloaded_partials.values()]
                perf = dict(update.get("perf") or {}) if isinstance(update.get("perf"), dict) else {}
                perf.update(
                    {
                        "eutherbooks_backend_elapsed_sec": time.perf_counter() - synth_started,
                        "eutherbooks_poll_count": poll_count,
                        "eutherbooks_downloaded_partial_count": len(downloaded_partials),
                    }
                )
                if first_partial_sec is not None:
                    perf["eutherbooks_first_partial_sec"] = first_partial_sec
                update["perf"] = perf
                progress_callback(update)

        try:
            submit_started = time.perf_counter()
            job = _request_json(f"{base_url}/v1/tts/jobs", payload, timeout)
            worker_job_id = str(job.get("id") or "").strip() or None
            submit_sec = time.perf_counter() - submit_started
            LOGGER.warning(
                "TTS_TRACE eutherbooks_worker_accepted output=%s worker_job=%s submit_sec=%.3f",
                output_path,
                job.get("id"),
                submit_sec,
            )
            status_url = _absolute_worker_url(base_url, str(job["status_url"]))

            deadline = time.monotonic() + float(os.environ.get("EUTHERBOOKS_EUTHERLINK_JOB_TIMEOUT", "1800"))
            status = job
            while status.get("status") not in {"done", "failed"}:
                if time.monotonic() > deadline:
                    raise TtsError("EutherLink TTS job timed out.")
                time.sleep(poll_interval)
                poll_count += 1
                poll_started = time.perf_counter()
                status = _request_json(status_url, None, timeout)
                poll_sec = time.perf_counter() - poll_started
                perf = dict(status.get("perf") or {}) if isinstance(status.get("perf"), dict) else {}
                perf.update(
                    {
                        "eutherbooks_submit_sec": submit_sec,
                        "eutherbooks_last_poll_sec": poll_sec,
                        "eutherbooks_poll_count": poll_count,
                        "eutherbooks_backend_elapsed_sec": time.perf_counter() - synth_started,
                    }
                )
                status["perf"] = perf
                publish_partials(status)

            if status.get("status") != "done":
                raise TtsError(str(status.get("error") or status.get("message") or "EutherLink TTS job failed."))
            publish_partials(status)

            audio_url = _absolute_worker_url(base_url, str(status.get("audio_url") or job["audio_url"]))
            final_download_started = time.perf_counter()
            _download_file(audio_url, temp_output, timeout)
            final_download_sec = time.perf_counter() - final_download_started
            LOGGER.warning(
                "TTS_TRACE eutherbooks_download output=%s worker_job=%s bytes=%s download_sec=%.3f total_sec=%.3f",
                output_path,
                job.get("id"),
                temp_output.stat().st_size if temp_output.exists() else 0,
                final_download_sec,
                time.perf_counter() - synth_started,
            )
            if abs(length_scale - 1.0) > 0.001:
                tempo_started = time.perf_counter()
                _apply_eutherlink_length_scale(temp_output, length_scale)
                tempo_sec = time.perf_counter() - tempo_started
                LOGGER.warning(
                    "TTS_TRACE eutherbooks_tempo output=%s worker_job=%s length_scale=%.3f atempo=%.6f bytes=%s tempo_sec=%.3f",
                    output_path,
                    job.get("id"),
                    length_scale,
                    1.0 / length_scale,
                    temp_output.stat().st_size if temp_output.exists() else 0,
                    tempo_sec,
                )
            else:
                tempo_sec = 0.0
            if progress_callback is not None:
                final_update = dict(status)
                perf = dict(final_update.get("perf") or {}) if isinstance(final_update.get("perf"), dict) else {}
                perf.update(
                    {
                        "eutherbooks_final_download_sec": final_download_sec,
                        "eutherbooks_final_tempo_sec": tempo_sec,
                        "eutherbooks_total_backend_sec": time.perf_counter() - synth_started,
                        "eutherbooks_final_bytes": temp_output.stat().st_size if temp_output.exists() else 0,
                    }
                )
                final_update["perf"] = perf
                final_update["partial_audio_paths"] = [str(path) for path in downloaded_partials.values()]
                progress_callback(final_update)
            os.replace(temp_output, output_path)
        except Exception:
            if worker_job_id is not None:
                _cancel_eutherlink_job(base_url, worker_job_id, timeout)
            raise
        finally:
            temp_output.unlink(missing_ok=True)


def _clamped_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _clamped_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _dots_template_name(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in {"tts", "instruction_tts", "text_to_audio", "tts_interleave"}:
        return value.strip().lower()
    return "tts"


def _dots_ode_method(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in {"euler", "midpoint"}:
        return value.strip().lower()
    return "euler"


def _short_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _stable_voice_seed(data: bytes) -> int:
    digest = hashlib.blake2s(data, digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF


def _positive_seed(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _eutherlink_length_scale(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if parsed != parsed:
        return 1.0
    return min(1.6, max(0.65, parsed))


def _apply_eutherlink_length_scale(path: Path, length_scale: float) -> None:
    atempo = 1.0 / length_scale
    tempo_path = path.with_name(f"{path.name}.tempo.wav")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-filter:a",
                f"atempo={atempo:.6f}",
                "-f",
                "wav",
                str(tempo_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.replace(tempo_path, path)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise TtsError(f"EutherLink audio tempo adjustment failed: {detail or exc}") from exc
    finally:
        tempo_path.unlink(missing_ok=True)


def _valid_voice_reference_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 600 or not value.endswith(".wav"):
        return ""
    root = Path(os.environ.get("EUTHERBOOKS_VOICE_REFERENCE_ROOT", "/home/nichlas/EutherOxide/.euther-host/user-data")).resolve()
    requested = Path(value).expanduser()
    candidates = [requested]
    if not requested.is_absolute():
        eutheroxide_root = Path(os.environ.get("EUTHERBOOKS_EUTHEROXIDE_ROOT", "/home/nichlas/EutherOxide"))
        candidates.append(eutheroxide_root / requested)
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if (path == root or root in path.parents) and path.is_file():
            return str(path)
    return ""


def _valid_voice_prompt_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip()[:500] if ch == "\t" or ord(ch) >= 32)

EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE = {
    "own-sv": "Solen går långsamt upp över skogen. Jag läser den här texten med min naturliga berättarröst, tydligt och lugnt, så att varje ord hörs klart.",
    "own-en": "The morning light moves slowly across the room. I read this text in my natural narrator voice, clearly and calmly, so every word is easy to hear.",
}
EUTHERLINK_PROMPT_TRANSCRIPTS = set(EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE.values())


def _own_voice_reference_path(voice_id: str, reference_path: str) -> str:
    expected_name = f"{voice_id}.wav"
    if reference_path and Path(reference_path).name == expected_name:
        return reference_path
    root = Path(os.environ.get("EUTHERBOOKS_VOICE_REFERENCE_ROOT", "/home/nichlas/EutherOxide/.euther-host/user-data")).resolve()
    fallback = root / "nichlas" / "eutherbooks" / "voices" / expected_name
    if fallback.is_file():
        return str(fallback)
    return reference_path


def _own_voice_prompt_text(voice_id: str, prompt_text: str) -> str:
    expected = EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE.get(voice_id, "")
    if not expected:
        return prompt_text
    if not prompt_text or prompt_text in EUTHERLINK_PROMPT_TRANSCRIPTS:
        return expected
    return prompt_text


def _use_eutherlink_prompt_transcript(prompt_text: str = "") -> bool:
    value = os.environ.get("EUTHERBOOKS_EUTHERLINK_USE_PROMPT_TRANSCRIPT", "").strip().lower()
    return value in {"1", "true", "yes", "on"} or prompt_text.strip() in EUTHERLINK_PROMPT_TRANSCRIPTS


def _dots_preset_prompt_text(voice_id: str, language: str) -> str:
    normalized_language = language.strip().lower()
    if voice_id.strip().lower().startswith("sv-") or normalized_language.startswith("sv"):
        return (
            "Solen lyser stilla över vägen. Jag läser den här korta referenstexten med jämn rytm, "
            "tydlig artikulation och naturliga pauser, så att rösten kan hållas konsekvent."
        )
    return (
        "Morning light rests quietly on the road. I read this short reference passage with steady rhythm, "
        "clear articulation, and natural pauses, so the voice can remain consistent."
    )


def _dots_preset_reference_path(
    *,
    base_url: str,
    timeout: float,
    poll_interval: float,
    model_backend: str,
    voice_id: str,
    language: str,
    voice_instruction: str,
    seed: int,
    template_name: Any,
    ode_method: Any,
    num_steps: Any,
    guidance_scale: Any,
    speaker_scale: Any,
    max_generate_length: Any,
) -> Path:
    reference_backend = os.environ.get("EUTHERBOOKS_DOTS_PRESET_REFERENCE_BACKEND", "voxcpm2").strip().lower()
    if reference_backend not in {"voxcpm2", "dots.tts-soar", "dots.tts-mf"}:
        reference_backend = "voxcpm2"
    cache_dir = _dots_preset_cache_dir() / _safe_cache_name(reference_backend)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_safe_cache_name(voice_id)}-{seed}.wav"
    if cache_path.is_file() and cache_path.stat().st_size > 44:
        return cache_path

    lock_dir = cache_path.with_suffix(".lock")
    lock_acquired = False
    deadline = time.monotonic() + float(os.environ.get("EUTHERBOOKS_DOTS_PRESET_LOCK_TIMEOUT", "240"))
    while not lock_acquired:
        try:
            lock_dir.mkdir()
            lock_acquired = True
        except FileExistsError:
            if cache_path.is_file() and cache_path.stat().st_size > 44:
                return cache_path
            if time.monotonic() > deadline:
                raise TtsError(f"Timed out waiting for Dots preset reference: {voice_id}")
            time.sleep(min(1.0, max(0.05, poll_interval)))

    try:
        if cache_path.is_file() and cache_path.stat().st_size > 44:
            return cache_path
        temp_path = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
        try:
            _render_dots_preset_reference(
                base_url=base_url,
                timeout=timeout,
                poll_interval=poll_interval,
                output_path=temp_path,
                model_backend=model_backend,
                voice_id=voice_id,
                language=language,
                voice_instruction=voice_instruction,
                seed=seed,
                reference_backend=reference_backend,
                template_name=template_name,
                ode_method=ode_method,
                num_steps=num_steps,
                guidance_scale=guidance_scale,
                speaker_scale=speaker_scale,
                max_generate_length=max_generate_length,
            )
            os.replace(temp_path, cache_path)
        finally:
            temp_path.unlink(missing_ok=True)
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass
    return cache_path


def _render_dots_preset_reference(
    *,
    base_url: str,
    timeout: float,
    poll_interval: float,
    output_path: Path,
    model_backend: str,
    voice_id: str,
    language: str,
    voice_instruction: str,
    seed: int,
    reference_backend: str,
    template_name: Any,
    ode_method: Any,
    num_steps: Any,
    guidance_scale: Any,
    speaker_scale: Any,
    max_generate_length: Any,
) -> None:
    payload: dict[str, Any] = {
        "text": _dots_preset_prompt_text(voice_id, language),
        "voice_instruction": voice_instruction,
        "language": language,
        "output_format": "wav",
        "model_backend": reference_backend,
        "seed": seed,
        "max_chunk_chars": 700,
    }
    if _is_dots_backend(reference_backend):
        payload.update(
            {
                "dots_template_name": template_name or "tts",
                "dots_ode_method": ode_method or "euler",
                "dots_num_steps": int(num_steps or 4),
                "dots_guidance_scale": float(guidance_scale if guidance_scale is not None else 1.2),
                "dots_speaker_scale": float(speaker_scale if speaker_scale is not None else 1.5),
                "dots_max_generate_length": int(max_generate_length or 500),
            }
        )
    LOGGER.warning(
        "TTS_TRACE eutherbooks_preset_reference_start voice=%s model_backend=%s reference_backend=%s seed=%s output=%s prompt_text_sha=%s",
        voice_id,
        model_backend,
        reference_backend,
        seed,
        output_path,
        _short_sha256(payload["text"].encode("utf-8")),
    )
    job = _request_json(f"{base_url}/v1/tts/jobs", payload, timeout)
    status_url = _absolute_worker_url(base_url, str(job["status_url"]))
    worker_job_id = str(job.get("id") or "")
    deadline = time.monotonic() + float(os.environ.get("EUTHERBOOKS_DOTS_PRESET_JOB_TIMEOUT", "900"))
    status = job
    try:
        while status.get("status") not in {"done", "failed"}:
            if time.monotonic() > deadline:
                raise TtsError(f"Dots preset reference job timed out for {voice_id}.")
            time.sleep(poll_interval)
            status = _request_json(status_url, None, timeout)
        if status.get("status") != "done":
            raise TtsError(str(status.get("error") or status.get("message") or "Dots preset reference job failed."))
        audio_url = _absolute_worker_url(base_url, str(status.get("audio_url") or job["audio_url"]))
        _download_file(audio_url, output_path, timeout)
        LOGGER.warning(
            "TTS_TRACE eutherbooks_preset_reference_done voice=%s model_backend=%s reference_backend=%s seed=%s worker_job=%s bytes=%s",
            voice_id,
            model_backend,
            reference_backend,
            seed,
            worker_job_id,
            output_path.stat().st_size if output_path.exists() else 0,
        )
    except Exception:
        if worker_job_id:
            _cancel_eutherlink_job(base_url, worker_job_id, timeout)
        raise


def _dots_preset_cache_dir() -> Path:
    configured = os.environ.get("EUTHERBOOKS_DOTS_PRESET_VOICE_DIR")
    if configured:
        return Path(configured).expanduser()
    data_dir = Path(os.environ.get("EUTHERBOOKS_DATA_DIR", "data")).expanduser()
    return data_dir / "preset-voices"


def _safe_cache_name(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "default"


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


def _eutherlink_model_backend(voice: str, option: Any) -> str:
    if isinstance(option, str) and option.strip().lower() in {"voxcpm2", "dots.tts-soar", "dots.tts-mf", "grapheneos-matcha-en", "auto-fallback"}:
        return option.strip().lower()
    normalized_voice = voice.strip().lower()
    if normalized_voice.startswith("auto-"):
        return "auto-fallback"
    if normalized_voice.startswith("grapheneos-matcha-"):
        return "grapheneos-matcha-en"
    if normalized_voice.startswith("dots-mf-"):
        return "dots.tts-mf"
    return "dots.tts-soar" if normalized_voice.startswith("dots-soar-") else "voxcpm2"


def _is_dots_backend(model_backend: str) -> bool:
    return model_backend in {"dots.tts-soar", "dots.tts-mf"}


def _needs_dots_reference(model_backend: str) -> bool:
    return model_backend in {"dots.tts-soar", "dots.tts-mf", "auto-fallback"}


def _eutherlink_voice_id(voice: str) -> str:
    value = voice.strip()
    lower = value.lower()
    if lower.startswith("dots-soar-"):
        return value[len("dots-soar-") :]
    if lower.startswith("dots-mf-"):
        return value[len("dots-mf-") :]
    if lower.startswith("auto-"):
        return value[len("auto-") :]
    return value


def _eutherlink_stable_preset_seed(voice: str) -> int | None:
    value = voice.strip()
    normalized = value.lower().replace("-", "_")
    if not value or normalized in {"own_sv", "own_en"}:
        return None
    material = f"eutherbooks:eutherlink:{normalized}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big") & 0x7FFFFFFF


def _eutherlink_voice_instruction(voice: str) -> str:
    base = "Keep one speaker identity for the whole chapter: same timbre, accent, age, energy, prosody, and pacing in every paragraph and every generated chunk. Never switch speaker, gender, dialect, or performance style between chunks."
    configured = os.environ.get(
        "EUTHERBOOKS_EUTHERLINK_VOICE_INSTRUCTION",
        os.environ.get(
            "EUTHERBOOKS_TTS_VOICE",
            "A warm, clear Swedish audiobook narrator with calm natural pacing.",
        ),
    )
    value = voice.strip()
    normalized = value.lower().replace("-", "_")
    if normalized in {"own_sv", "own_en"}:
        return ""
    presets = {
        "sv": "A warm, clear Swedish audiobook narrator with calm natural pacing, measured tempo, and consistent Swedish pronunciation.",
        "se": "A warm, clear Swedish audiobook narrator with calm natural pacing, measured tempo, and consistent Swedish pronunciation.",
        "sv_female": "A warm adult female Swedish audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "female": "A warm adult female Swedish audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "sv_female_warm": "A warm adult female Swedish audiobook narrator, close and friendly, with relaxed pacing and consistent Stockholm-neutral Swedish pronunciation.",
        "sv_female_clear": "A precise adult female Swedish narrator with bright clarity, careful consonants, steady measured pacing, and consistent Swedish accent.",
        "sv_female_soft": "A soft adult female Swedish bedtime storyteller with gentle tone, low intensity, slow relaxed pacing, and smooth phrasing.",
        "sv_female_deep": "A lower-pitched adult female Swedish narrator with rich timbre, calm confidence, and slow measured pacing.",
        "sv_female_elder": "An older female Swedish storyteller with warm character, lived-in tone, clear diction, and unhurried pacing.",
        "sv_male": "A warm adult male Swedish audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "male": "A warm adult male Swedish audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "sv_male_warm": "A warm adult male Swedish audiobook narrator, close and friendly, with relaxed pacing and consistent Stockholm-neutral Swedish pronunciation.",
        "sv_male_clear": "A precise adult male Swedish narrator with clean diction, crisp consonants, steady measured pacing, and consistent Swedish accent.",
        "sv_male_deep": "A deep adult male Swedish narrator with resonant timbre, calm authority, and slow measured pacing.",
        "sv_male_soft": "A soft adult male Swedish storyteller with gentle tone, low intensity, slow relaxed pacing, and smooth phrasing.",
        "sv_male_elder": "An older male Swedish storyteller with warm character, weathered timbre, clear diction, and unhurried pacing.",
        "sv_neutral": "A calm neutral Swedish audiobook narrator with clear pronunciation, steady measured pacing, and stable tone.",
        "neutral": "A calm neutral Swedish audiobook narrator with clear pronunciation, steady measured pacing, and stable tone.",
        "sv_neutral_calm": "A calm neutral Swedish audiobook narrator with balanced tone, clean pronunciation, and steady measured pacing.",
        "sv_neutral_news": "A crisp Swedish documentary narrator with neutral delivery, high intelligibility, controlled pacing, and stable accent.",
        "sv_neutral_theatre": "An expressive Swedish theatre narrator with controlled drama, clear diction, consistent voice identity, and audiobook pacing.",
        "sv_whisper": "A quiet Swedish bedtime narrator with intimate near-whisper softness, slow pacing, and clear understandability.",
        "sv_character_bright": "A bright lively Swedish character narrator with energetic warmth, clear diction, playful tone, and consistent voice identity.",
        "sv_character_gritty": "A gritty Swedish character narrator with rougher texture, lower intensity, clear diction, measured pacing, and consistent tone.",
        "en": "A warm, clear English audiobook narrator with calm measured pacing and consistent General American pronunciation.",
        "en_us": "A warm, clear English audiobook narrator with calm measured pacing and consistent General American pronunciation.",
        "en_female": "A warm adult female English audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "en_female_warm": "A warm adult female English audiobook narrator, close and friendly, with relaxed pacing and consistent General American pronunciation.",
        "en_female_clear": "A precise adult female English narrator with bright clarity, careful consonants, steady measured pacing, and consistent accent.",
        "en_female_soft": "A soft adult female English bedtime storyteller with gentle tone, low intensity, slow relaxed pacing, and smooth phrasing.",
        "en_female_deep": "A lower-pitched adult female English narrator with rich timbre, calm confidence, and slow measured pacing.",
        "en_female_elder": "An older female English storyteller with warm character, lived-in tone, clear diction, and unhurried pacing.",
        "en_male": "A warm adult male English audiobook narrator with clear pronunciation, measured calm pacing, and natural emotional nuance.",
        "en_male_warm": "A warm adult male English audiobook narrator, close and friendly, with relaxed pacing and consistent General American pronunciation.",
        "en_male_clear": "A precise adult male English narrator with clean diction, crisp consonants, steady measured pacing, and consistent accent.",
        "en_male_deep": "A deep adult male English narrator with resonant timbre, calm authority, and slow measured pacing.",
        "en_male_soft": "A soft adult male English storyteller with gentle tone, low intensity, slow relaxed pacing, and smooth phrasing.",
        "en_male_elder": "An older male English storyteller with warm character, weathered timbre, clear diction, and unhurried pacing.",
        "en_neutral": "A calm neutral English audiobook narrator with clear pronunciation, steady measured pacing, and stable tone.",
        "en_neutral_calm": "A calm neutral English audiobook narrator with balanced tone, clean pronunciation, and steady measured pacing.",
        "en_neutral_news": "A crisp English documentary narrator with neutral delivery, high intelligibility, controlled pacing, and stable accent.",
        "en_neutral_theatre": "An expressive English theatre narrator with controlled drama, clear diction, consistent voice identity, and audiobook pacing.",
        "en_whisper": "A quiet English bedtime narrator with intimate near-whisper softness, slow pacing, and clear understandability.",
        "en_character_bright": "A bright lively English character narrator with energetic warmth, clear diction, playful tone, and consistent voice identity.",
        "en_character_gritty": "A gritty English character narrator with rougher texture, lower intensity, clear diction, measured pacing, and consistent tone.",
    }
    if normalized in presets:
        return f"{presets[normalized]} {base}"
    if not value or normalized in {"sv_se", "sv_se_nst", "en_us_lessac", "custom"}:
        return f"{configured} {base}"
    if value.endswith(".onnx") or "/" in value:
        return f"{configured} {base}"
    return f"{value} {base}"

def eutherlink_health() -> dict[str, Any]:
    base_url = os.environ.get("EUTHERBOOKS_EUTHERLINK_URL", "http://192.168.32.88:8765").rstrip("/")
    timeout = float(os.environ.get("EUTHERBOOKS_EUTHERLINK_TIMEOUT", "15"))
    return _request_json(f"{base_url}/health", None, timeout)


def _request_json(url: str, payload: dict[str, Any] | None, timeout: float, method: str | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method=method or ("GET" if payload is None else "POST"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise TtsError(f"EutherLink request failed: {exc}") from exc


def _cancel_eutherlink_job(base_url: str, worker_job_id: str, timeout: float) -> None:
    try:
        _request_json(f"{base_url}/v1/tts/jobs/{worker_job_id}", None, timeout, method="DELETE")
    except TtsError as exc:
        LOGGER.warning("TTS_TRACE eutherbooks_worker_cancel_failed worker_job=%s error=%s", worker_job_id, exc)


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
