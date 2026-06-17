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


def test_eutherlink_dots_voice_defaults_to_longer_generate_length(monkeypatch, tmp_path: Path) -> None:
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
    assert captured["dots_max_generate_length"] == 500


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
        {
            "voice_reference_path": str(sample),
            "voice_prompt_text": "Detta sade jag i samplet.",
            "dots_template_name": "instruction_tts",
            "dots_ode_method": "midpoint",
            "dots_num_steps": 14,
            "dots_guidance_scale": 1.4,
            "dots_speaker_scale": 1.8,
            "dots_max_generate_length": 640,
        },
    )

    assert captured["model_backend"] == "dots.tts-soar"
    assert captured["voice_instruction"] == ""
    assert captured["dots_template_name"] == "instruction_tts"
    assert captured["dots_ode_method"] == "midpoint"
    assert captured["dots_num_steps"] == 14
    assert captured["dots_guidance_scale"] == 1.4
    assert captured["dots_speaker_scale"] == 1.8
    assert captured["dots_max_generate_length"] == 640
    assert "reference_wav_base64" in captured
    assert "prompt_wav_base64" in captured
    assert captured["prompt_text"] == "Detta sade jag i samplet."


def test_eutherlink_dots_preset_uses_generated_prompt_audio(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}
    reference_payloads: list[dict[str, object]] = []
    main_payloads: list[dict[str, object]] = []
    statuses = iter(
        [
            {"status": "done", "audio_url": "/preset-audio"},
            {"status": "done", "audio_url": "/audio"},
        ]
    )

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setenv("EUTHERBOOKS_DATA_DIR", str(tmp_path / "data"))

    def fake_request_json(url, payload, timeout):
        if payload is not None:
            if payload["text"] == tts._dots_preset_prompt_text("en-female-deep", "en"):
                reference_payloads.append(dict(payload))
                return {"id": "preset", "status_url": "/preset-status", "audio_url": "/preset-audio", "status": "queued"}
            captured.update(payload)
            main_payloads.append(dict(payload))
            return {"id": "main", "status_url": "/status", "audio_url": "/audio", "status": "queued"}
        return next(statuses)

    def fake_download_file(url, output_path, timeout):
        output_path.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + (b"preset" if "preset" in url else b"final"))

    monkeypatch.setattr(tts, "_request_json", fake_request_json)
    monkeypatch.setattr(tts, "_download_file", fake_download_file)

    tts.EutherLinkBackend().synthesize(
        "Hello",
        output,
        "en",
        "dots-mf-en-female-deep",
        {"model_backend": "dots.tts-mf"},
    )

    assert captured["model_backend"] == "dots.tts-mf"
    assert captured["voice_instruction"]
    assert captured["seed"] == tts._eutherlink_stable_preset_seed("en-female-deep")
    assert reference_payloads[0]["model_backend"] == "voxcpm2"
    assert reference_payloads[0]["seed"] == tts._eutherlink_stable_preset_seed("en-female-deep")
    assert reference_payloads[0]["voice_instruction"] == captured["voice_instruction"]
    assert "reference_wav_base64" in captured
    assert "prompt_wav_base64" in captured
    assert captured["prompt_text"] == tts._dots_preset_prompt_text("en-female-deep", "en")
    assert len(main_payloads) == 1


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


def test_eutherlink_grapheneos_matcha_backend_routes_to_worker(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(tts, "_temporary_output_path", lambda path: tmp_path / ".out.tmp")
    monkeypatch.setattr(tts, "_request_json", lambda url, payload, timeout: captured.update(payload or {}) or ({"status_url": "/status", "audio_url": "/audio", "status": "queued"} if payload is not None else {"status": "done", "audio_url": "/audio"}))
    monkeypatch.setattr(tts, "_download_file", lambda url, output_path, timeout: output_path.write_bytes(b"wav"))

    tts.EutherLinkBackend().synthesize(
        "Hello",
        output,
        "en",
        "grapheneos-matcha-en",
        {"model_backend": "grapheneos-matcha-en"},
    )

    assert captured["model_backend"] == "grapheneos-matcha-en"
    assert captured["language"] == "en"


def test_eutherlink_downloads_stream_partials(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}
    callbacks: list[dict[str, object]] = []
    statuses = iter(
        [
            {"id": "job1", "status": "running", "partial_audio_urls": ["/partials/one.wav"]},
            {"id": "job1", "status": "done", "audio_url": "/audio", "partial_audio_urls": ["/partials/one.wav"]},
        ]
    )

    monkeypatch.setenv("EUTHERBOOKS_EUTHERLINK_POLL_INTERVAL", "0")

    def fake_request_json(url, payload, timeout):
        if payload is not None:
            captured.update(payload)
            return {"id": "job1", "status_url": "/status", "audio_url": "/audio", "status": "queued"}
        return next(statuses)

    def fake_download_file(url, output_path, timeout):
        output_path.write_bytes(b"final" if url.endswith("/audio") else b"partial")

    monkeypatch.setattr(tts, "_request_json", fake_request_json)
    monkeypatch.setattr(tts, "_download_file", fake_download_file)

    tts.EutherLinkBackend().synthesize(
        "Hej",
        output,
        "sv",
        "sv-female",
        {"model_backend": "voxcpm2"},
        progress_callback=callbacks.append,
    )

    partial = tmp_path / "out.stream-001.wav"
    assert captured["model_backend"] == "voxcpm2"
    assert output.read_bytes() == b"final"
    assert partial.read_bytes() == b"partial"
    assert callbacks[-1]["partial_audio_paths"] == [str(partial)]


def test_eutherlink_own_voice_sends_builtin_reading_prompt_as_transcript(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sample")
    output = tmp_path / "out.wav"
    captured: dict[str, object] = {}
    prompt = tts.EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE["own-sv"]

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


def test_eutherlink_dots_own_sv_overrides_stale_own_en_state(monkeypatch, tmp_path: Path) -> None:
    sample_root = tmp_path / "user-data"
    sample_sv = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-sv.wav"
    sample_en = sample_root / "nichlas" / "eutherbooks" / "voices" / "own-en.wav"
    sample_sv.parent.mkdir(parents=True)
    sample_sv.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"sv")
    sample_en.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"en")
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
        {
            "voice_reference_path": str(sample_en),
            "voice_prompt_text": tts.EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE["own-en"],
            "model_backend": "dots.tts-soar",
        },
    )

    assert captured["prompt_text"] == tts.EUTHERLINK_PROMPT_TRANSCRIPT_BY_VOICE["own-sv"]
    assert captured["prompt_wav_base64"] != ""
    assert captured["reference_wav_base64"] != ""
