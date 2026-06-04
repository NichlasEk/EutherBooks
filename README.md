# EutherBooks

EutherBooks is a local ebook-to-audiobook service module intended for an EutherOxide server.
Drop legally sourced ebooks into `library/`, let the service index them, and generate audio with a local TTS backend.

The first version is deliberately small:

- Recursive library scanning for `.epub`, `.txt`, and `.md`.
- EPUB metadata and text extraction using Python standard libraries.
- TTS job queue with generated `.wav` files under `data/audio/`.
- Swappable TTS backend interface, currently `espeak` and `piper`.
- FastAPI endpoints for books, chapters, jobs, and generated audio.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn eutherbooks.api:app --host 0.0.0.0 --port 8088
```

Then open:

```text
http://localhost:8088/docs
```

## Library

Place books in `library/`, including nested folders:

```text
library/
  svenska/
    selma-lagerlof/
      nils-holgersson.epub
  english/
    sample.txt
```

The API uses a stable ID based on each file's path inside `library/`.

## Configuration

Environment variables:

| Name | Default | Description |
| --- | --- | --- |
| `EUTHERBOOKS_LIBRARY_DIR` | `library` | Ebook root directory. |
| `EUTHERBOOKS_DATA_DIR` | `data` | Persistent service data. |
| `EUTHERBOOKS_AUDIO_DIR` | `data/audio` | Generated audio files. |
| `EUTHERBOOKS_CACHE_DIR` | `data/cache` | Reserved cache directory. |
| `EUTHERBOOKS_DEFAULT_LANGUAGE` | `sv` | Default language for TTS jobs. |
| `EUTHERBOOKS_TTS_BACKEND` | `espeak` | `espeak` or `piper`. |
| `EUTHERBOOKS_TTS_VOICE` | `sv` | Voice name or Piper model path. |
| `EUTHERBOOKS_PIPER_BIN` | unset | Optional path to the Piper TTS binary. |

## Piper TTS

Piper is the recommended neural backend for the current EutherServer hardware.
The Debian package named `piper` is a mouse configuration tool, not Piper TTS, so EutherBooks prefers `EUTHERBOOKS_PIPER_BIN` or `tools/piper/piper`.

Download local Piper assets:

```bash
scripts/download_piper_assets.sh
```

Then run with Swedish Piper by setting:

```bash
export EUTHERBOOKS_TTS_BACKEND=piper
export EUTHERBOOKS_TTS_VOICE=/home/nichlas/EutherBooks/models/piper/sv_SE-nst-medium.onnx
export EUTHERBOOKS_PIPER_BIN=/home/nichlas/EutherBooks/tools/piper/piper
```

## API

- `GET /health`
- `GET /books`
- `GET /books/{book_id}`
- `GET /books/{book_id}/chapters`
- `GET /books/{book_id}/chapters/{chapter_index}`
- `POST /books/{book_id}/tts`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /audio/{audio_path}`

Example TTS request:

```bash
curl -X POST http://localhost:8088/books/BOOK_ID/tts \
  -H 'content-type: application/json' \
  -d '{"language":"sv","voice":"sv","chapters":[0]}'
```

## Next Good Steps

- Add authenticated upload/import endpoints for known public-domain sources.
- Add a database when job history and user accounts need richer querying.
- Add Piper Swedish voice model management.
- Add EPUB spine-order parsing for better chapter order.
- Add per-user playback progress and bookmarking.
