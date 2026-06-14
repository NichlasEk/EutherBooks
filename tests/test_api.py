from __future__ import annotations

from fastapi.routing import APIRoute

from eutherbooks.api import create_app


def test_books_endpoint_uses_dependency_not_query_param() -> None:
    app = create_app()

    route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/books")

    assert [param.name for param in route.dependant.query_params] == []


def test_upload_book_endpoint_uses_name_query_param() -> None:
    app = create_app()

    route = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/books/upload")

    assert [param.name for param in route.dependant.query_params] == ["name"]



def test_eutherlink_voices_include_matching_english_presets(monkeypatch) -> None:
    monkeypatch.setenv("EUTHERBOOKS_TTS_BACKEND", "eutherlink")
    app = create_app()
    voices = next(route.endpoint for route in app.routes if isinstance(route, APIRoute) and route.path == "/voices")()

    sv_presets = [voice for voice in voices if voice.path.startswith("preset:sv-")]
    en_presets = [voice for voice in voices if voice.path.startswith("preset:en-")]

    assert len(en_presets) == len(sv_presets)
    assert all(voice.default_seed for voice in sv_presets + en_presets)
    assert all(voice.default_length_scale for voice in sv_presets + en_presets)


def test_eutherlink_voices_include_dots_model_choices(monkeypatch) -> None:
    monkeypatch.setenv("EUTHERBOOKS_TTS_BACKEND", "eutherlink")
    app = create_app()
    voices = next(route.endpoint for route in app.routes if isinstance(route, APIRoute) and route.path == "/voices")()

    dots_voices = [voice for voice in voices if voice.model_backend in {"dots.tts-soar", "dots.tts-mf"}]
    base_presets = {
        voice.id
        for voice in voices
        if voice.model_backend == "voxcpm2" and voice.path.startswith("preset:") and voice.id != "custom"
    }
    mf_ids = {voice.id for voice in dots_voices if voice.model_backend == "dots.tts-mf"}
    soar_ids = {voice.id for voice in dots_voices if voice.model_backend == "dots.tts-soar"}

    assert {"dots-mf-own-sv", "dots-mf-own-en"} <= mf_ids
    assert {"dots-soar-own-sv", "dots-soar-own-en"} <= soar_ids
    assert {f"dots-mf-{voice_id}" for voice_id in base_presets} <= mf_ids
    assert {f"dots-soar-{voice_id}" for voice_id in base_presets} <= soar_ids
    assert all(voice.default_seed for voice in dots_voices if voice.path.startswith("preset:"))
    voices_by_id = {voice.id: voice for voice in voices}
    for voice_id in base_presets:
        assert voices_by_id[f"dots-mf-{voice_id}"].default_seed == voices_by_id[voice_id].default_seed
        assert voices_by_id[f"dots-soar-{voice_id}"].default_seed == voices_by_id[voice_id].default_seed

def test_eutherlink_health_includes_dots_status(monkeypatch) -> None:
    monkeypatch.setenv("EUTHERBOOKS_TTS_BACKEND", "eutherlink")
    import eutherbooks.api as api_module

    monkeypatch.setattr(
        api_module,
        "eutherlink_health",
        lambda: {"ok": True, "dots_tts": {"status": "ready", "model_loaded": True}},
    )
    app = create_app()
    health = next(route.endpoint for route in app.routes if isinstance(route, APIRoute) and route.path == "/health")()

    assert health["tts_backend"] == "eutherlink"
    assert health["dots_tts"] == {"status": "ready", "model_loaded": True}
