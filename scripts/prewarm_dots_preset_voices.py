#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from eutherbooks.api import _eutherlink_voices
from eutherbooks.tts import (
    _dots_preset_reference_path,
    _eutherlink_stable_preset_seed,
    _eutherlink_voice_id,
    _eutherlink_voice_instruction,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-generate Dots TTS preset voice reference WAVs.")
    parser.add_argument("--model", choices=["dots.tts-mf", "dots.tts-soar", "all"], default="all")
    parser.add_argument("--voice", action="append", default=[], help="Preset voice id to include; may be repeated.")
    parser.add_argument("--force", action="store_true", help="Delete existing cached references before regenerating.")
    parser.add_argument("--base-url", default=os.environ.get("EUTHERBOOKS_EUTHERLINK_URL", "http://192.168.32.88:8765"))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("EUTHERBOOKS_EUTHERLINK_TIMEOUT", "15")))
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("EUTHERBOOKS_EUTHERLINK_POLL_INTERVAL", "1.0")),
    )
    args = parser.parse_args()

    wanted_voices = set(args.voice)
    voices = [
        voice
        for voice in _eutherlink_voices()
        if voice.path.startswith("preset:")
        and voice.id != "custom"
        and voice.model_backend in {"dots.tts-mf", "dots.tts-soar"}
        and (args.model == "all" or voice.model_backend == args.model)
        and (not wanted_voices or voice.id in wanted_voices or _eutherlink_voice_id(voice.id) in wanted_voices)
    ]

    seen: set[tuple[str, int]] = set()
    for voice in voices:
        voice_id = _eutherlink_voice_id(voice.id)
        seed = voice.default_seed or _eutherlink_stable_preset_seed(voice_id)
        if seed is None:
            continue
        # MF and SOAR share the same reference sample when the reference backend is VoxCPM2.
        key = (voice_id, seed)
        if key in seen:
            continue
        seen.add(key)
        target = _expected_cache_path(voice_id, seed)
        if args.force:
            target.unlink(missing_ok=True)
        print(f"prewarm {voice.id} -> {target}", flush=True)
        path = _dots_preset_reference_path(
            base_url=args.base_url.rstrip("/"),
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            model_backend=str(voice.model_backend),
            voice_id=voice_id,
            language=voice.language,
            voice_instruction=_eutherlink_voice_instruction(voice_id),
            seed=seed,
            template_name="tts",
            ode_method="euler",
            num_steps=4 if voice.model_backend == "dots.tts-mf" else 10,
            guidance_scale=1.2,
            speaker_scale=1.5,
            max_generate_length=500,
        )
        print(f"ready {voice.id}: {path} ({path.stat().st_size} bytes)", flush=True)
    print(f"prewarmed {len(seen)} preset voice reference(s)", flush=True)
    return 0


def _expected_cache_path(voice_id: str, seed: int) -> Path:
    from eutherbooks.tts import _dots_preset_cache_dir, _safe_cache_name

    reference_backend = os.environ.get("EUTHERBOOKS_DOTS_PRESET_REFERENCE_BACKEND", "voxcpm2").strip().lower()
    if reference_backend not in {"voxcpm2", "dots.tts-soar", "dots.tts-mf"}:
        reference_backend = "voxcpm2"
    return _dots_preset_cache_dir() / _safe_cache_name(reference_backend) / f"{_safe_cache_name(voice_id)}-{seed}.wav"


if __name__ == "__main__":
    raise SystemExit(main())
