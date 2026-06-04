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
