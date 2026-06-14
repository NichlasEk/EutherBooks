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

    dots_voices = [voice for voice in voices if voice.model_backend == "dots.tts-soar"]

    assert {voice.id for voice in dots_voices} == {"dots-soar-own-sv", "dots-soar-own-en"}
    assert all(voice.path.startswith("user:own-") for voice in dots_voices)
