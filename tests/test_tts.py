from __future__ import annotations

from pathlib import Path

from eutherbooks import tts


def test_piper_binary_prefers_configured_env(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "piper"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("EUTHERBOOKS_PIPER_BIN", str(binary))

    assert tts._piper_binary() == binary


def test_piper_binary_rejects_non_tts_piper_on_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EUTHERBOOKS_PIPER_BIN", raising=False)
    monkeypatch.setattr(tts.Path, "resolve", lambda self: self)
    monkeypatch.setattr(tts, "which", lambda name: "/usr/bin/piper")

    def fake_run(*args, **kwargs):
        class Result:
            stdout = "GTK application options\n"

        return Result()

    monkeypatch.setattr(tts.subprocess, "run", fake_run)

    assert tts._piper_binary() is None


def test_piper_model_path_maps_swedish_alias() -> None:
    assert tts._piper_model_path("sv", "sv") == Path("models/piper/sv_SE-nst-medium.onnx")


def test_piper_model_path_allows_env_override(monkeypatch, tmp_path: Path) -> None:
    model = tmp_path / "custom.onnx"
    monkeypatch.setenv("EUTHERBOOKS_PIPER_VOICE_EN", str(model))

    assert tts._piper_model_path("en", "en") == model


def test_eutherlink_own_voice_uses_reference_only_by_default(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.delenv("EUTHERBOOKS_EUTHERLINK_USE_PROMPT_TRANSCRIPT", raising=False)
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")

    def fake_request_json(url, payload, timeout):
        if payload is not None:
            captured.update(payload)
            return {"status_url": "/status", "audio_url": "/audio", "status": "queued"}
        return {"status": "done", "audio_url": "/audio"}

    def fake_download_file(url, output_path, timeout):
        output_path.write_bytes(b"wav")

    monkeypatch.setattr(tts, "_request_json", fake_request_json)
    monkeypatch.setattr(tts, "_download_file", fake_download_file)

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "own-sv",
        {"voice_reference_path": str(sample), "voice_prompt_text": "not an exact transcript", "seed": 123456},
    )

    assert output.read_bytes() == b"wav"
    assert captured["voice_instruction"] == ""
    assert "reference_wav_base64" in captured
    assert captured["seed"] == 123456
    assert "prompt_wav_base64" not in captured
    assert "prompt_text" not in captured


def test_eutherlink_own_voice_can_send_prompt_transcript_when_enabled(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.setenv("EUTHERBOOKS_EUTHERLINK_USE_PROMPT_TRANSCRIPT", "true")
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "own-sv",
        {"voice_reference_path": str(sample), "voice_prompt_text": "Detta sade jag i samplet."},
    )

    assert captured["voice_instruction"] == ""
    assert "reference_wav_base64" in captured
    assert "prompt_wav_base64" in captured
    assert captured["prompt_text"] == "Detta sade jag i samplet."


def test_eutherlink_dots_voice_sends_model_backend_and_prompt(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "dots-soar-own-sv",
        {"voice_reference_path": str(sample), "voice_prompt_text": "Detta sade jag i samplet."},
    )

    assert captured["model_backend"] == "dots.tts-soar"
    assert captured["voice_instruction"] == ""
    assert "reference_wav_base64" in captured
    assert "prompt_wav_base64" in captured
    assert captured["prompt_text"] == "Detta sade jag i samplet."


def test_eutherlink_explicit_model_backend_option_wins(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-male-warm",
        {"model_backend": "voxcpm2"},
    )

    assert captured["model_backend"] == "voxcpm2"


def test_eutherlink_own_voice_sends_builtin_reading_prompt_as_transcript(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}
    prompt = next(iter(tts.EUTHERLINK_PROMPT_TRANSCRIPTS))

    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.delenv("EUTHERBOOKS_EUTHERLINK_USE_PROMPT_TRANSCRIPT", raising=False)
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "own-sv",
        {"voice_reference_path": str(sample), "voice_prompt_text": prompt},
    )

    assert captured["voice_instruction"] == ""
    assert "reference_wav_base64" in captured
    assert "prompt_wav_base64" in captured
    assert captured["prompt_text"] == prompt


def test_eutherlink_clamps_too_low_inference_steps(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-female",
        {"inference_timesteps": 1},
    )

    assert captured["inference_timesteps"] == 10

def test_eutherlink_own_voice_accepts_eutheroxide_relative_reference_path(monkeypatch, tmp_path: Path) -> None:
    eutheroxide_root = tmp_path / "EutherOxide"
    sample_root = eutheroxide_root / ".euther-host" / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setenv("EUTHERBOOKS_EUTHEROXIDE_ROOT", str(eutheroxide_root))
    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "own-sv",
        {"voice_reference_path": ".euther-host/user-data/nichlas/eutherbooks/voices/own-sv.wav"},
    )

    assert captured["voice_instruction"] == ""
    assert "reference_wav_base64" in captured

def test_eutherlink_own_voice_zero_seed_uses_sample_seed(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample_bytes = b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample"
    sample.write_bytes(sample_bytes)
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setenv("EUTHERBOOKS_VOICE_REFERENCE_ROOT", str(sample_root))
    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "own-sv",
        {"voice_reference_path": str(sample), "seed": 0},
    )

    assert captured["seed"] == tts._stable_voice_seed(sample_bytes)
    assert "reference_wav_base64" in captured


def test_eutherlink_preset_auto_seed_is_stable(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-male-warm",
        {"seed": 0},
    )

    assert captured["seed"] == tts._eutherlink_stable_preset_seed("sv-male-warm")


def test_eutherlink_explicit_preset_seed_wins(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-male-warm",
        {"seed": 777},
    )

    assert captured["seed"] == 777

def test_eutherlink_applies_length_scale_tempo(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    tempo_calls: list[tuple[Path, float]] = []

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: {"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"})
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))
    monkeypatch.setattr(tts, "_apply_eutherlink_length_scale", lambda path, length_scale: tempo_calls.append((path, length_scale)))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-female",
        {"length_scale": 1.35},
    )

    assert output.read_bytes() == b"wav"
    assert tempo_calls == [(tmp_path / ".out.tmp", 1.35)]


def test_eutherlink_length_scale_one_skips_tempo(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    tempo_calls: list[tuple[Path, float]] = []

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: {"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"})
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))
    monkeypatch.setattr(tts, "_apply_eutherlink_length_scale", lambda path, length_scale: tempo_calls.append((path, length_scale)))

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-female",
        {"length_scale": 1.0},
    )

    assert output.read_bytes() == b"wav"
    assert tempo_calls == []
