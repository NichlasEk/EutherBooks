from __future__ import annotations

from types import SimpleNamespace

from scripts import prewarm_dots_preset_voices


def test_prewarm_deduplicates_mf_and_soar(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []

    monkeypatch.setenv("EUTHERBOOKS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        prewarm_dots_preset_voices,
        "_eutherlink_voices",
        lambda: [
            SimpleNamespace(
                id="dots-mf-en-female-soft",
                path="preset:en-female-soft",
                model_backend="dots.tts-mf",
                language="en",
                default_seed=123,
            ),
            SimpleNamespace(
                id="dots-soar-en-female-soft",
                path="preset:en-female-soft",
                model_backend="dots.tts-soar",
                language="en",
                default_seed=123,
            ),
        ],
    )

    def fake_reference_path(**kwargs):
        calls.append(kwargs)
        path = prewarm_dots_preset_voices._expected_cache_path(kwargs["voice_id"], kwargs["seed"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF\0\0\0\0WAVEpreset")
        return path

    monkeypatch.setattr(prewarm_dots_preset_voices, "_dots_preset_reference_path", fake_reference_path)

    assert prewarm_dots_preset_voices.main() == 0
    assert len(calls) == 1
    assert calls[0]["voice_id"] == "en-female-soft"
