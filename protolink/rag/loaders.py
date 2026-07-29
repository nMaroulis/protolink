"""Built-in source loading for managed ProtoLink knowledge bases."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from collections.abc import Mapping
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from protolink.tools.builtins._network import _http_get

from .errors import OptionalRAGDependencyError
from .models import Document, stable_id

_TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".csv",
    ".html",
    ".htm",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".markdown",
    ".py",
    ".rst",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
_HTML_SUFFIXES = {".html", ".htm"}
_IGNORED_DIRECTORY_NAMES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}


class AutoLoader:
    """Load common local, inline, and HTTP sources with safe defaults.

    Local directories are traversed recursively. Text-like files are decoded
    as UTF-8 with replacement for malformed bytes; HTML is reduced to visible
    text; PDFs use the optional ``pypdf`` package. Unsupported binary files are
    rejected instead of being silently embedded as corrupted text.

    Args:
        recursive: Whether directory sources include nested files.
        request_timeout: Timeout for HTTP and HTTPS sources.
        user_agent: User-Agent header sent by the built-in URL loader.
        max_content_bytes: Maximum accepted remote response size.
    """

    def __init__(
        self,
        *,
        recursive: bool = True,
        request_timeout: float = 20.0,
        user_agent: str = "ProtoLink-RAG/1",
        max_content_bytes: int = 5_000_000,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be greater than zero")
        if max_content_bytes <= 0:
            raise ValueError("max_content_bytes must be greater than zero")
        self.recursive = recursive
        self.request_timeout = request_timeout
        self.user_agent = user_agent
        self.max_content_bytes = max_content_bytes

    async def load(
        self,
        source: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[Document]:
        """Normalize one source into documents.

        ``source`` may be a :class:`Document`, ``Path``, local path string,
        HTTP(S) URL, bytes value, or inline text string.
        """
        common_metadata = dict(metadata or {})
        if isinstance(source, Document):
            return [
                Document(
                    text=source.text,
                    source=source.source,
                    metadata={**source.metadata, **common_metadata},
                    id=source.id,
                    media_type=source.media_type,
                )
            ]
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="replace")
            identifier = stable_id("inline", text)
            return [
                Document(
                    text=text,
                    source=f"inline:{identifier}",
                    metadata=common_metadata,
                )
            ]
        if isinstance(source, Path):
            return await asyncio.to_thread(self._load_path, source.expanduser(), common_metadata)
        if not isinstance(source, str):
            raise TypeError(
                f"Knowledge sources must be Document, Path, str, or bytes; received {type(source).__name__}"
            )

        if _is_http_url(source):
            return await asyncio.to_thread(self._load_url, source, common_metadata)

        candidate = Path(source).expanduser()
        if candidate.exists():
            return await asyncio.to_thread(self._load_path, candidate, common_metadata)

        identifier = stable_id("inline", source)
        return [
            Document(
                text=source,
                source=f"inline:{identifier}",
                metadata=common_metadata,
            )
        ]

    def _load_path(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        if path.is_dir():
            pattern = "**/*" if self.recursive else "*"
            documents: list[Document] = []
            for child in sorted(path.glob(pattern)):
                if not child.is_file() or any(part in _IGNORED_DIRECTORY_NAMES for part in child.parts):
                    continue
                if child.suffix.casefold() not in {*_TEXT_SUFFIXES, ".pdf"}:
                    continue
                documents.extend(self._load_file(child, metadata))
            return documents
        if not path.is_file():
            raise FileNotFoundError(f"Knowledge source is not a regular file: {path}")
        return self._load_file(path, metadata)

    def _load_file(self, path: Path, metadata: dict[str, Any]) -> list[Document]:
        suffix = path.suffix.casefold()
        source = str(path.resolve())
        file_metadata = {
            **metadata,
            "filename": path.name,
            "extension": suffix,
        }
        if suffix == ".pdf":
            return self._load_pdf(path, source, file_metadata)
        if suffix not in _TEXT_SUFFIXES:
            raise ValueError(
                f"Unsupported knowledge file type '{suffix or '<none>'}'. Pass a custom Loader for this source."
            )

        text = path.read_text(encoding="utf-8", errors="replace")
        media_type = mimetypes.guess_type(path.name)[0] or "text/plain"
        if suffix in _HTML_SUFFIXES:
            text = _visible_html_text(text)
        elif suffix == ".json":
            text = _pretty_json(text)
        if not text.strip():
            return []
        return [
            Document(
                text=text,
                source=source,
                metadata=file_metadata,
                media_type=media_type,
            )
        ]

    @staticmethod
    def _load_pdf(path: Path, source: str, metadata: dict[str, Any]) -> list[Document]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise OptionalRAGDependencyError(
                "PDF ingestion requires the optional 'pypdf' package. "
                'Install it with `pip install "protolink[rag-pdf]"`.'
            ) from exc

        reader = PdfReader(str(path))
        documents: list[Document] = []
        for page_index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            documents.append(
                Document(
                    text=text,
                    source=source,
                    metadata={**metadata, "page": page_index + 1},
                    id=stable_id("doc", source, page_index + 1, text),
                    media_type="application/pdf",
                )
            )
        return documents

    def _load_url(self, url: str, metadata: dict[str, Any]) -> list[Document]:
        response = _http_get(
            url,
            headers={"User-Agent": self.user_agent},
            timeout=self.request_timeout,
            max_bytes=self.max_content_bytes,
            max_redirects=4,
        )
        content = response.body
        final_url = response.url
        content_headers = Message()
        content_headers["content-type"] = response.headers.get(
            "content-type",
            "application/octet-stream",
        )
        content_type = content_headers.get_content_type()
        charset = content_headers.get_content_charset() or "utf-8"

        if content_type == "application/pdf" or urlparse(final_url).path.casefold().endswith(".pdf"):
            raise OptionalRAGDependencyError(
                "Remote PDF loading is not enabled by the dependency-free loader. "
                "Download the file first or provide a custom Loader."
            )

        text = content.decode(charset, errors="replace")
        if content_type == "text/html":
            text = _visible_html_text(text)
        elif content_type == "application/json":
            text = _pretty_json(text)
        elif not (
            content_type.startswith("text/")
            or content_type in {"application/javascript", "application/xml"}
            or content_type.endswith("+json")
            or content_type.endswith("+xml")
        ):
            raise ValueError(
                f"Unsupported remote knowledge content type '{content_type}'. "
                "Provide a custom Loader for binary content."
            )
        if not text.strip():
            return []
        return [
            Document(
                text=text,
                source=final_url,
                metadata={**metadata, "url": final_url},
                media_type=content_type,
            )
        ]


class _HTMLTextExtractor(HTMLParser):
    """Collect visible HTML data while dropping executable and style blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
        elif tag in {"br", "p", "div", "li", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "div", "li", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _visible_html_text(value: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(value)
    text = " ".join("".join(extractor.parts).split())
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _pretty_json(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        return value


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
