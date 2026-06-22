from __future__ import annotations

import html
import os
import re
import tempfile
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .models import Chapter


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_PDF_PAGE_BREAK_RE = re.compile(r"\f+")
_PDF_MARGIN_LINE_COUNT = 4
_PDF_MARGIN_MIN_PAGES = 3
_PDF_MARGIN_MIN_FRACTION = 0.35
_PDF_TEXT_EXTRACTION_MODES = (("-raw",), ("-layout",), ())


def clean_html_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return _SPACE_RE.sub(" ", value).strip()


def split_plain_text(text: str, chunk_size: int = 5_000) -> list[Chapter]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chapters: list[Chapter] = []
    current: list[str] = []
    current_len = 0

    for block in blocks or [text.strip()]:
        if current and current_len + len(block) > chunk_size:
            chapters.append(_chapter_from_blocks(len(chapters), current))
            current = []
            current_len = 0
        current.append(block)
        current_len += len(block)

    if current:
        chapters.append(_chapter_from_blocks(len(chapters), current))

    return chapters


def _chapter_from_blocks(index: int, blocks: list[str]) -> Chapter:
    first_line = blocks[0].splitlines()[0].strip()
    title = first_line[:80] if len(first_line) > 8 else f"Del {index + 1}"
    return Chapter(index=index, title=title, text="\n\n".join(blocks))


def extract_text_file(path: Path) -> list[Chapter]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return split_plain_text(raw)


def extract_pdf(path: Path) -> list[Chapter]:
    text = clean_pdf_repeated_margins(_extract_pdf_text(path)).strip()
    if not text:
        return extract_pdf_ocr(path)
    return split_plain_text(text)


def extract_pdf_ocr(path: Path) -> list[Chapter]:
    total_pages = pdf_page_count(path)
    cache_dir = pdf_ocr_cache_dir(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_pages = sorted(cache_dir.glob("*.txt"))
    if not cached_pages:
        batch_size = max(1, int(os.environ.get("EUTHERBOOKS_OCR_BATCH_PAGES", "12")))
        for page in range(1, min(total_pages, batch_size) + 1):
            ocr_pdf_page(path, cache_dir, page)
        cached_pages = sorted(cache_dir.glob("*.txt"))

    page_texts: list[tuple[int, str]] = []
    for page_path in cached_pages:
        text = page_path.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) < 20:
            continue
        page_number = int(page_path.stem)
        page_texts.append((page_number, text))

    cleaned_pages = clean_pdf_page_repeated_margins([text for _page_number, text in page_texts])
    chapters = []
    for (page_number, _text), cleaned_text in zip(page_texts, cleaned_pages):
        text = cleaned_text.strip()
        if len(text) < 20:
            continue
        chapters.append(Chapter(index=len(chapters), title=f"Page {page_number}", text=text))
    if not chapters:
        raise RuntimeError("PDF OCR produced no readable text")
    return chapters


def clean_pdf_repeated_margins(text: str) -> str:
    pages = _split_pdf_pages(text)
    if len(pages) < _PDF_MARGIN_MIN_PAGES:
        return text
    cleaned_pages = clean_pdf_page_repeated_margins(pages)
    separator = "\n\n"
    return separator.join(page.strip() for page in cleaned_pages if page.strip())


def clean_pdf_page_repeated_margins(pages: list[str]) -> list[str]:
    candidates = _pdf_repeated_margin_candidates(pages)
    return [_clean_pdf_page_margins(page, candidates) for page in pages]


def pdf_margin_cleanup_preview(text: str, max_pages: int = 8) -> dict[str, object]:
    pages = _split_pdf_pages(text)
    candidates = _pdf_repeated_margin_candidates(pages)
    cleaned_pages = [_clean_pdf_page_margins(page, candidates) for page in pages]
    samples = []
    for page_number, (before, after) in enumerate(zip(pages, cleaned_pages), start=1):
        if len(samples) >= max_pages:
            break
        if before != after:
            samples.append(
                {
                    "page": page_number,
                    "removed": _removed_margin_lines(before, after),
                    "before": _preview_text(before),
                    "after": _preview_text(after),
                }
            )
    return {
        "page_count": len(pages),
        "candidate_lines": sorted(candidates),
        "sample_pages": samples,
    }


def extract_pdf_margin_cleanup_preview(path: Path, max_pages: int = 8) -> dict[str, object]:
    return pdf_margin_cleanup_preview(_extract_pdf_text(path), max_pages=max_pages)


def _extract_pdf_text(path: Path) -> str:
    last_error: subprocess.CalledProcessError | None = None
    for mode in _PDF_TEXT_EXTRACTION_MODES:
        try:
            result = subprocess.run(
                ["pdftotext", "-enc", "UTF-8", *mode, str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as error:
            raise RuntimeError("pdftotext is required to read PDF files") from error
        except subprocess.CalledProcessError as error:
            last_error = error
            continue
        if result.stdout.strip():
            return result.stdout
    if last_error is not None:
        detail = (last_error.stderr or "").strip()
        message = f"PDF text extraction failed: {detail}" if detail else "PDF text extraction failed"
        raise RuntimeError(message) from last_error
    return ""


def _split_pdf_pages(text: str) -> list[str]:
    pages = [page for page in _PDF_PAGE_BREAK_RE.split(text) if page.strip()]
    return pages or [text]


def _pdf_repeated_margin_candidates(pages: list[str]) -> set[str]:
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    for page in pages:
        seen_on_page = set()
        for line in _pdf_margin_lines(page):
            normalized = _normalize_pdf_margin_line(line)
            if not normalized:
                continue
            seen_on_page.add(normalized)
            examples.setdefault(normalized, line.strip())
        for normalized in seen_on_page:
            counts[normalized] = counts.get(normalized, 0) + 1

    threshold = max(_PDF_MARGIN_MIN_PAGES, int(len(pages) * _PDF_MARGIN_MIN_FRACTION + 0.999))
    return {examples[normalized] for normalized, count in counts.items() if count >= threshold}


def _pdf_margin_lines(page: str) -> list[str]:
    lines = [line for line in page.splitlines() if line.strip()]
    top = lines[:_PDF_MARGIN_LINE_COUNT]
    bottom = lines[-_PDF_MARGIN_LINE_COUNT:] if len(lines) > _PDF_MARGIN_LINE_COUNT else []
    return top + bottom


def _clean_pdf_page_margins(page: str, candidates: set[str]) -> str:
    cleaned = _remove_pdf_page_number_lines(page)
    if candidates:
        cleaned = _remove_pdf_margin_lines(cleaned, candidates)
    return cleaned


def _remove_pdf_page_number_lines(page: str) -> str:
    lines = page.splitlines()
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    removable = set(nonempty_indexes[:_PDF_MARGIN_LINE_COUNT])
    removable.update(nonempty_indexes[-_PDF_MARGIN_LINE_COUNT:])
    kept = [
        line
        for index, line in enumerate(lines)
        if index not in removable or not _is_pdf_page_number_line(line)
    ]
    return "\n".join(kept).strip()


def _is_pdf_page_number_line(line: str) -> bool:
    normalized = _SPACE_RE.sub(" ", line).strip()
    if not normalized or len(normalized) > 32:
        return False
    return bool(
        re.fullmatch(r"[\W_]*\d{1,5}[\W_]*", normalized)
        or re.fullmatch(r"[\W_]*\d{1,5}\s+(?:/+\s*)?\d{1,5}[\W_]*", normalized)
        or re.fullmatch(r"[\W_]*\d{1,5}\s+of\s+\d{1,5}[\W_]*", normalized, flags=re.IGNORECASE)
    )


def _remove_pdf_margin_lines(page: str, candidates: set[str]) -> str:
    normalized_candidates = {_normalize_pdf_margin_line(line) for line in candidates}
    lines = page.splitlines()
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    removable = set(nonempty_indexes[:_PDF_MARGIN_LINE_COUNT])
    removable.update(nonempty_indexes[-_PDF_MARGIN_LINE_COUNT:])
    kept = [
        line
        for index, line in enumerate(lines)
        if index not in removable or _normalize_pdf_margin_line(line) not in normalized_candidates
    ]
    return "\n".join(kept).strip()


def _removed_margin_lines(before: str, after: str) -> list[str]:
    before_lines = [line.strip() for line in before.splitlines() if line.strip()]
    after_lines = [line.strip() for line in after.splitlines() if line.strip()]
    after_counts: dict[str, int] = {}
    for line in after_lines:
        normalized = _normalize_pdf_margin_line(line)
        after_counts[normalized] = after_counts.get(normalized, 0) + 1
    removed = []
    for line in before_lines:
        normalized = _normalize_pdf_margin_line(line)
        if after_counts.get(normalized, 0):
            after_counts[normalized] -= 1
        elif line not in removed:
            removed.append(line)
    return removed


def _normalize_pdf_margin_line(line: str) -> str:
    normalized = _SPACE_RE.sub(" ", line).strip()
    if not normalized:
        return ""
    if re.fullmatch(r"[\W_]*\d+[\W_]*", normalized):
        return ""
    normalized = re.sub(r"(?<!\w)\d{1,4}(?!\w)", " ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    if not re.search(r"[^\W\d_]", normalized):
        return ""
    if len(normalized) > 120:
        return ""
    return normalized.casefold()


def _preview_text(text: str, max_chars: int = 700) -> str:
    compact = "\n".join(line.rstrip() for line in text.strip().splitlines() if line.strip())
    return compact[:max_chars]


def pdf_ocr_cached_page_count(path: Path) -> int:
    return len(sorted(pdf_ocr_cache_dir(path).glob("*.txt")))


def pdf_ocr_next_batch(path: Path, batch_size: int | None = None) -> int:
    total_pages = pdf_page_count(path)
    cache_dir = pdf_ocr_cache_dir(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    size = batch_size or max(1, int(os.environ.get("EUTHERBOOKS_OCR_BATCH_PAGES", "12")))
    start_page = pdf_ocr_cached_page_count(path) + 1
    end_page = min(total_pages, start_page + size - 1)
    if start_page > total_pages:
        return 0
    for page in range(start_page, end_page + 1):
        ocr_pdf_page(path, cache_dir, page)
    return end_page - start_page + 1


def pdf_page_count(path: Path) -> int:
    try:
        result = subprocess.run(
            ["pdfinfo", str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError("pdfinfo is required to OCR PDF files") from error
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not determine PDF page count")
    return int(match.group(1))


def pdf_ocr_cache_dir(path: Path) -> Path:
    return path.parent / ".eutherbooks-cache" / f"{path.name}.ocr"


def ocr_pdf_page(path: Path, cache_dir: Path, page: int) -> None:
    output_path = cache_dir / f"{page:04d}.txt"
    if output_path.exists():
        return
    language = os.environ.get("EUTHERBOOKS_OCR_LANG", "eng+swe")
    with tempfile.TemporaryDirectory(prefix="eutherbooks-ocr-") as tmp:
        prefix = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-r", "200", "-f", str(page), "-l", str(page), "-png", str(path), str(prefix)],
            check=True,
            capture_output=True,
        )
        images = sorted(Path(tmp).glob("page-*.png"))
        if not images:
            raise RuntimeError(f"PDF page {page} could not be rendered for OCR")
        result = subprocess.run(
            ["tesseract", str(images[0]), "stdout", "-l", language],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    output_path.write_text(result.stdout.strip(), encoding="utf-8")


def extract_epub_metadata(path: Path) -> tuple[str | None, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            opf_name = _find_opf(archive)
            if opf_name is None:
                return None, None
            root = ElementTree.fromstring(archive.read(opf_name))
    except (ElementTree.ParseError, KeyError, zipfile.BadZipFile):
        return None, None

    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    title = _xml_text(root.find(".//dc:title", ns))
    author = _xml_text(root.find(".//dc:creator", ns))
    return title, author


def extract_epub(path: Path) -> list[Chapter]:
    with zipfile.ZipFile(path) as archive:
        html_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
            and not name.endswith("/")
        ]
        html_names.sort()

        chapters: list[Chapter] = []
        for name in html_names:
            raw = archive.read(name).decode("utf-8", errors="replace")
            text = clean_html_text(raw)
            if len(text) < 40:
                continue
            title = _title_from_html(raw) or Path(name).stem.replace("_", " ").replace("-", " ")
            chapters.append(Chapter(index=len(chapters), title=title[:100], text=text))

    return chapters


def extract_chapters(path: Path) -> list[Chapter]:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return extract_epub(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".txt", ".md"}:
        return extract_text_file(path)
    raise ValueError(f"Unsupported ebook format: {path.suffix}")


def _find_opf(archive: zipfile.ZipFile) -> str | None:
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    except (ElementTree.ParseError, KeyError):
        return None
    for element in container.iter():
        if element.tag.endswith("rootfile"):
            full_path = element.attrib.get("full-path")
            if full_path:
                return full_path
    return None


def _title_from_html(raw: str) -> str | None:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        match = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", raw)
    if not match:
        return None
    title = clean_html_text(match.group(1))
    return title or None


def _xml_text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    text = _SPACE_RE.sub(" ", element.text).strip()
    return text or None
