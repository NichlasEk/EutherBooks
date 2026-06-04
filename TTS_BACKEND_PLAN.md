# EutherBooks TTS Backend Plan

## Goal

Build EutherBooks so it can run well on the current EutherServer first, while leaving a clean path for higher-quality AI speech later.

Current server constraints:

- CPU: Intel Pentium J2900, 4 cores
- GPU: integrated Intel only
- RAM: 8 GB
- OS: Debian 13

This means the first production backend should be CPU-friendly and reliable. Larger neural voice-cloning models should be optional workers, not the default service path.

## Backend Strategy

### 1. Keep `espeak` as emergency fallback

Purpose:

- Always have a tiny local backend.
- Useful when model files are missing or Piper is broken.
- Good for testing queue, API, and frontend behavior.

Status:

- Already implemented.
- Kept as fallback, but systemd now uses Piper.

### 2. Make `piper` the first real neural backend

Purpose:

- Better voice quality than `espeak`.
- Runs on CPU.
- Low memory use.
- Practical on the current EutherServer.
- Supports English voices and Swedish via `sv_SE/nst`.

Implementation status:

- Basic `PiperBackend` already exists in `eutherbooks/tts.py`.
- It expects `EUTHERBOOKS_TTS_VOICE` to point at a `.onnx` model.
- Local Piper TTS binary is installed under `tools/piper/piper`.
- Swedish and English Piper voices are downloaded under `models/piper/`.
- `eutherbooks.service` now defaults to Swedish Piper.

Next tasks:

1. Add friendly voice aliases so the API can accept `sv`, `en`, `sv_SE_nst`, etc.
2. Let the frontend choose Swedish or English voice per job.
3. Add a small model integrity/checksum command.
4. Consider removing generated audio for old backend runs if disk usage grows.

Recommended initial voices:

- Swedish: `sv_SE-nst-medium`
- English: start with an `en_US` medium voice such as `lessac` or another proven Piper voice after listening tests.

### 3. Add `chatterbox` as future AI-quality backend

Purpose:

- Higher-quality AI speech.
- Voice cloning from short reference audio.
- English first, Swedish as experimental but promising.
- Useful when there is a GPU or a stronger worker machine.

Why not default now:

- Chatterbox is much heavier than Piper.
- Current server has no NVIDIA GPU.
- CPU-only generation may be slow and memory-heavy.
- It should not block EutherBooks startup or normal audiobook playback.

Implementation shape:

- Add `ChatterboxBackend` behind `EUTHERBOOKS_TTS_BACKEND=chatterbox`.
- Load model lazily on first job, not during API startup.
- Make it optional dependency, not part of the default install.
- Support reference voice file through `EUTHERBOOKS_TTS_VOICE_REF`.
- Add a per-backend chunk-size setting because AI models may prefer shorter text chunks than Piper.
- Add clear timeout/error reporting to jobs.

### 4. Consider `kokoro` for fast English later

Purpose:

- Very good English quality for a small model.
- Apache-2.0 license.
- Potentially a nice middle tier between Piper and Chatterbox.

Why later:

- Swedish support is less certain than Piper/Chatterbox.
- EutherBooks needs stable Swedish/English first.

## Model Files and Git Policy

Do not commit large model weights directly to this repository by default, even when the model license is MIT or Apache-2.0.

Reasons:

- Git history grows permanently; deleting later does not really remove the weight from old commits.
- Piper and AI model files can be hundreds of MB.
- GitHub normal repositories are not a good model registry.
- Updating model files becomes awkward and slow.
- It mixes source code history with binary asset distribution.

Preferred policy:

- Commit code, config examples, checksums, and download scripts.
- Store downloaded model files under a local ignored directory such as `models/`.
- Add `models/` to `.gitignore`.
- Keep a `models/README.md` or `models/piper/README.md` with exact source URLs, licenses, and checksums.

Acceptable exceptions:

- A tiny config file or model metadata file.
- A very small test fixture, if needed for tests.
- Git LFS only if we intentionally decide this repo should distribute model assets.

## First Milestone: Working Piper on EutherServer

Definition of done:

- `piper` binary is installed or available in a local tools directory. Done.
- Swedish and English Piper model files exist locally. Done.
- `EUTHERBOOKS_TTS_BACKEND=piper` works from the command line. Done.
- Generating one API job produces playable `.wav`. Done.
- Frontend Audiobooks player can play generated audio over LAN and internet. Uses the existing `/eutherbooks` proxy path.
- `eutherbooks.service` starts automatically after reboot with Piper enabled. Done.

Suggested steps:

1. Add ignored local model directories.
2. Download Piper binary if Debian package is not available or not suitable.
3. Download Swedish and English `.onnx` plus `.onnx.json` files.
4. Test Piper manually:

   ```bash
   echo "Hej, det här är EutherBooks." | piper --model models/piper/sv_SE-nst-medium.onnx --output_file /tmp/eutherbooks-piper-test.wav
   ```

5. Update `eutherbooks.service`:

   ```ini
   Environment=EUTHERBOOKS_TTS_BACKEND=piper
   Environment=EUTHERBOOKS_TTS_VOICE=/home/nichlas/EutherBooks/models/piper/sv_SE-nst-medium.onnx
   ```

6. Restart service and generate a chapter from the frontend.

## Second Milestone: Backend Selection

Definition of done:

- The API can choose backend/voice per job safely.
- Defaults still come from environment variables.
- The frontend can show at least a simple voice/backend selector.
- Invalid backend/voice combinations fail with clear job errors.

Recommended behavior:

- Default backend: `piper`
- Default Swedish voice: local Piper Swedish model
- Default English voice: local Piper English model
- `espeak` kept as fallback
- `chatterbox` hidden unless dependencies are installed

## Third Milestone: Chatterbox Experimental Worker

Definition of done:

- Chatterbox can be installed in a separate virtualenv or worker process.
- EutherBooks can enqueue Chatterbox jobs without making the main API slow to start.
- Failures do not break Piper/espeak jobs.
- A reference voice file can be configured and documented.

Recommended shape:

- `EUTHERBOOKS_TTS_BACKEND=chatterbox`
- `EUTHERBOOKS_CHATTERBOX_DEVICE=cpu|cuda`
- `EUTHERBOOKS_CHATTERBOX_REF=/path/to/reference.wav`
- `EUTHERBOOKS_CHATTERBOX_MAX_CHARS=800`

On the current server, this should be treated as experimental only.

## Current Recommendation

Build order:

1. Piper Swedish and English working end to end.
2. Piper voice alias/config polish.
3. Optional Kokoro English experiment.
4. Chatterbox worker when stronger hardware is available.

Do not put large model weights directly into normal Git commits. Use ignored local model directories plus documented download commands and checksums.
