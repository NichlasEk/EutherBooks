from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .models import Chapter


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


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

