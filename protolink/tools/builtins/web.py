"""Dependency-free public web search and bounded URL fetching tools."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
from html.parser import HTMLParser
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import Field

from protolink.tools.tool import Tool

from ._network import _http_get, _HttpResponse

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
_SEARCH_RESPONSE_BYTES = 2_000_000
_FETCH_RESPONSE_BYTES = 1_000_000
_SEARCH_TIMEOUT_SECONDS = 10.0
_FETCH_TIMEOUT_SECONDS = 10.0
_SEARCH_REQUEST_URL_CHARS = 8192

_SearchQuery = Annotated[
    str,
    Field(min_length=1, max_length=400, description="Web search query, limited to 400 characters and 50 words."),
]
_MaxResults = Annotated[int, Field(ge=1, le=10, description="Maximum number of normalized results, from 1 to 10.")]
_Freshness = Literal["any", "day", "week", "month", "year"]
_SearchEngine = Annotated[
    Literal["brave", "duckduckgo"],
    Field(description="Search provider: Brave by default, or keyless best-effort DuckDuckGo HTML search."),
]
_PublicUrl = Annotated[
    str,
    Field(min_length=1, max_length=2048, description="Public HTTP or HTTPS URL on its standard port."),
]
_MaxChars = Annotated[
    int,
    Field(ge=1, le=50_000, description="Maximum returned text characters, from 1 to 50000."),
]

_BRAVE_FRESHNESS_CODES: dict[_Freshness, str | None] = {
    "any": None,
    "day": "pd",
    "week": "pw",
    "month": "pm",
    "year": "py",
}
_DUCKDUCKGO_FRESHNESS_CODES: dict[_Freshness, str | None] = {
    "any": None,
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_EXPLICIT_TEXT_MEDIA_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/json",
        "application/rss+xml",
        "application/xml",
    }
)
_WHITESPACE_RE = re.compile(r"\s+")
_DUCKDUCKGO_REDIRECT_HOSTS = frozenset({"duckduckgo.com", "www.duckduckgo.com"})
_DUCKDUCKGO_SPONSORED_CLASSES = frozenset(
    {
        "badge--ad",
        "result--ad",
        "result__badge--ad",
        "results--ads",
    }
)
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


def _attribute(attrs: list[tuple[str, str | None]], name: str) -> str:
    """Return one case-insensitive HTML attribute value."""
    normalized_name = name.lower()
    for key, value in attrs:
        if key.lower() == normalized_name:
            return value or ""
    return ""


def _class_tokens(attrs: list[tuple[str, str | None]]) -> frozenset[str]:
    """Return normalized CSS class tokens from an HTML tag."""
    return frozenset(_attribute(attrs, "class").lower().split())


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract bounded, sponsored-aware results from DuckDuckGo's non-JavaScript page."""

    def __init__(self, max_results: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_results = max_results
        self.results: list[dict[str, Any]] = []
        self.more_results_available = False
        self.explicit_no_results = False
        self.challenge_detected = False
        self.incomplete_result = False
        self._result_depth = 0
        self._result_is_ad = False
        self._title_href = ""
        self._title_chunks: list[str] = []
        self._snippet_chunks: list[str] = []
        self._title_chars = 0
        self._snippet_chars = 0
        self._capture: Literal["title", "snippet"] | None = None
        self._capture_depth = 0

    def _start_result(self, classes: frozenset[str]) -> None:
        """Start one recognized organic-result container."""
        self._result_depth = 1
        self._result_is_ad = bool(classes.intersection(_DUCKDUCKGO_SPONSORED_CLASSES))
        self._title_href = ""
        self._title_chunks = []
        self._snippet_chunks = []
        self._title_chars = 0
        self._snippet_chars = 0
        self._capture = None
        self._capture_depth = 0

    def _append_capture(self, data: str) -> None:
        """Append provider text while bounding parser-side accumulation."""
        if self._capture == "title" and self._title_chars < 1_000:
            value = data[: 1_000 - self._title_chars]
            self._title_chunks.append(value)
            self._title_chars += len(value)
        elif self._capture == "snippet" and self._snippet_chars < 4_000:
            value = data[: 4_000 - self._snippet_chars]
            self._snippet_chunks.append(value)
            self._snippet_chars += len(value)

    def _finish_result(self) -> None:
        """Normalize and retain the current result when it is safe and complete."""
        title = _clean_inline_text("".join(self._title_chunks), limit=500)
        url = _duckduckgo_result_url(self._title_href)
        if title and url:
            result: dict[str, Any] = {
                "title": title,
                "url": url,
                "snippet": _clean_inline_text("".join(self._snippet_chunks), limit=2000),
                "sponsored": self._result_is_ad,
            }
            if len(self.results) < self.max_results:
                self.results.append(result)
            else:
                self.more_results_available = True
        self._result_depth = 0
        self._capture = None
        self._capture_depth = 0

    def _observe_navigation(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record provider-control markers outside result text."""
        classes = _class_tokens(attrs)
        element_id = _attribute(attrs, "id").lower()
        action = _attribute(attrs, "action").lower().partition("?")[0].rstrip("/")
        if tag == "form" and (element_id == "challenge-form" or action.endswith("/anomaly.js")):
            self.challenge_detected = True
        if any(token == "anomaly-modal" or token.startswith("anomaly-modal__") for token in classes):
            self.challenge_detected = True
        if any(token == "no-results" or token.startswith("no-results__") for token in classes):
            self.explicit_no_results = True
        if "result--more" in classes:
            self.more_results_available = True
        if tag == "input" and _attribute(attrs, "type").lower() == "submit":
            if _attribute(attrs, "value").strip().lower() == "next":
                self.more_results_available = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track result containers, nested text, ads, and pagination."""
        normalized = tag.lower()
        self._observe_navigation(normalized, attrs)
        classes = _class_tokens(attrs)

        if not self._result_depth:
            is_organic = {"result", "web-result"}.issubset(classes)
            is_sponsored = "result" in classes and bool(classes.intersection(_DUCKDUCKGO_SPONSORED_CLASSES))
            if normalized == "div" and (is_organic or is_sponsored):
                self._start_result(classes)
            return

        if normalized == "div":
            self._result_depth += 1
        if classes.intersection(_DUCKDUCKGO_SPONSORED_CLASSES):
            self._result_is_ad = True

        if self._capture is not None:
            if normalized not in _HTML_VOID_TAGS:
                self._capture_depth += 1
            elif normalized == "br":
                self._append_capture(" ")
            return

        if normalized == "a" and "result__a" in classes and not self._title_href:
            self._title_href = _attribute(attrs, "href")
            self._capture = "title"
            self._capture_depth = 1
        elif "result__snippet" in classes:
            self._capture = "snippet"
            self._capture_depth = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Observe self-closing pagination and line-break elements."""
        normalized = tag.lower()
        self._observe_navigation(normalized, attrs)
        if self._capture is not None and normalized == "br":
            self._append_capture(" ")

    def handle_endtag(self, tag: str) -> None:
        """Close nested captures and finalize complete result containers."""
        if not self._result_depth:
            return
        normalized = tag.lower()
        if self._capture is not None and normalized not in _HTML_VOID_TAGS:
            self._capture_depth -= 1
            if self._capture_depth <= 0:
                self._capture = None
                self._capture_depth = 0
        if normalized == "div":
            self._result_depth -= 1
            if self._result_depth == 0:
                self._finish_result()

    def handle_data(self, data: str) -> None:
        """Collect title or snippet text from the active result."""
        if self._result_depth and self._capture is not None:
            self._append_capture(data)
        elif not self._result_depth and data.strip().lower().startswith("no results"):
            self.explicit_no_results = True

    def finish(self) -> None:
        """Record an incomplete final result rather than accepting partial markup."""
        if self._result_depth:
            self.incomplete_result = True
            self._result_depth = 0
            self._capture = None


class _ReadableHTMLParser(HTMLParser):
    """Extract a compact title and readable text without executing markup."""

    _BLOCK_TAGS = frozenset(
        {
            "article",
            "aside",
            "blockquote",
            "br",
            "dd",
            "div",
            "dl",
            "dt",
            "figcaption",
            "figure",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "li",
            "main",
            "nav",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "td",
            "th",
            "tr",
            "ul",
        }
    )
    _SKIP_TAGS = frozenset({"canvas", "noscript", "script", "style", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track skipped/title regions and preserve useful block boundaries."""
        del attrs
        normalized = tag.lower()
        if normalized in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if normalized == "title":
            self._title_depth += 1
        if normalized in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Preserve a boundary for self-closing block elements such as ``br``."""
        del attrs
        if not self._skip_depth and tag.lower() in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Leave skipped/title regions and preserve useful block boundaries."""
        normalized = tag.lower()
        if normalized in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if normalized in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        """Collect visible text and the page title."""
        if self._skip_depth:
            return
        if self._title_depth:
            self._title_chunks.append(data)
            return
        self._chunks.append(data)

    @property
    def title(self) -> str:
        """Return the normalized document title."""
        return _clean_inline_text(" ".join(self._title_chunks), limit=500)

    @property
    def text(self) -> str:
        """Return visible text with compact paragraph boundaries."""
        lines = []
        for raw_line in "".join(self._chunks).splitlines():
            line = _clean_inline_text(raw_line)
            if line:
                lines.append(line)
        return "\n".join(lines)


def _clean_inline_text(value: Any, *, limit: int | None = None) -> str:
    """Normalize provider or document text into a compact plain string."""
    if not isinstance(value, str):
        return ""
    normalized = _WHITESPACE_RE.sub(" ", html.unescape(value)).strip()
    return normalized if limit is None else normalized[:limit]


def _valid_result_url(value: Any) -> str:
    """Return a normalized web result URL or an empty string."""
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 or character in '<>"{}|\\^`'
        for character in value
    ):
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname:
        return ""
    try:
        normalized_host = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    try:
        normalized_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        netloc = normalized_host
    else:
        netloc = f"[{normalized_host}]" if normalized_ip.version == 6 else normalized_host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _duckduckgo_result_url(value: Any) -> str:
    """Unwrap one known DuckDuckGo redirect without requesting it."""
    if not isinstance(value, str) or len(value) > 4096:
        return ""
    candidate = urljoin("https://duckduckgo.com/", value)
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname in _DUCKDUCKGO_REDIRECT_HOSTS and parsed.path.rstrip("/") == "/l":
        try:
            params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=8)
        except ValueError:
            return ""
        destinations = params.get("uddg", [])
        if len(destinations) != 1:
            return ""
        return _valid_result_url(destinations[0])
    return _valid_result_url(candidate)


def _brave_api_key() -> str:
    """Load and validate the Brave credential without retaining it on a Tool."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "web_search requires BRAVE_SEARCH_API_KEY. Create a Brave Search API key and export it before running."
        )
    if len(api_key) > 512 or not api_key.isascii() or any(not 33 <= ord(character) <= 126 for character in api_key):
        raise RuntimeError("BRAVE_SEARCH_API_KEY contains invalid characters")
    return api_key


def _decode_json(response: _HttpResponse) -> dict[str, Any]:
    """Decode a provider response as a JSON object."""
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (RecursionError, ValueError) as exc:
        raise RuntimeError("Brave Search returned an invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Brave Search returned an unexpected response shape")
    return payload


def _normalize_search_results(payload: dict[str, Any], max_results: int) -> tuple[list[dict[str, Any]], bool]:
    """Normalize provider results into a small stable result contract."""
    web = payload.get("web")
    if web is None:
        raw_results: Any = []
    elif isinstance(web, dict):
        raw_results = web.get("results", [])
    else:
        raise RuntimeError("Brave Search returned an unexpected web result shape")
    if not isinstance(raw_results, list):
        raise RuntimeError("Brave Search returned an unexpected result list")

    results: list[dict[str, Any]] = []
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        title = _clean_inline_text(raw_result.get("title"), limit=500)
        url = _valid_result_url(raw_result.get("url"))
        if not title or not url:
            continue
        result = {
            "title": title,
            "url": url,
            "snippet": _clean_inline_text(raw_result.get("description"), limit=2000),
            "sponsored": False,
        }
        published_at = _clean_inline_text(raw_result.get("page_age"), limit=100)
        if published_at:
            result["published_at"] = published_at
        age = _clean_inline_text(raw_result.get("age"), limit=100)
        if age:
            result["age"] = age
        results.append(result)
        if len(results) >= max_results:
            break

    query_metadata = payload.get("query")
    more_results = bool(query_metadata.get("more_results_available")) if isinstance(query_metadata, dict) else False
    return results, more_results


async def _search_brave(
    query: str,
    max_results: int,
    freshness: _Freshness,
) -> tuple[list[dict[str, Any]], bool]:
    """Execute one bounded Brave Search API request."""
    params: dict[str, str | int] = {
        "q": query,
        "count": max_results,
        "result_filter": "web",
        "safesearch": "moderate",
        "text_decorations": "false",
    }
    freshness_code = _BRAVE_FRESHNESS_CODES[freshness]
    if freshness_code is not None:
        params["freshness"] = freshness_code
    request_url = f"{_BRAVE_SEARCH_URL}?{urlencode(params)}"
    response = await asyncio.to_thread(
        _http_get,
        request_url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": _brave_api_key(),
        },
        timeout=_SEARCH_TIMEOUT_SECONDS,
        max_bytes=_SEARCH_RESPONSE_BYTES,
        max_redirects=0,
        max_url_chars=_SEARCH_REQUEST_URL_CHARS,
    )
    return _normalize_search_results(_decode_json(response), max_results)


def _decode_duckduckgo_results(response: _HttpResponse, max_results: int) -> tuple[list[dict[str, Any]], bool]:
    """Decode one best-effort DuckDuckGo HTML response without bypassing blockers."""
    content_type = response.headers.get("content-type", "")
    media_type = _media_type(content_type)
    if media_type not in _HTML_MEDIA_TYPES:
        raise RuntimeError(f"DuckDuckGo returned unsupported content type {media_type!r}; expected HTML")
    try:
        decoded = response.body.decode(_charset(content_type), errors="replace")
    except LookupError as exc:
        raise RuntimeError("DuckDuckGo returned an unknown character encoding") from exc

    parser = _DuckDuckGoHTMLParser(max_results)
    try:
        parser.feed(decoded)
        parser.close()
        parser.finish()
    except Exception as exc:
        raise RuntimeError("DuckDuckGo returned malformed search HTML") from exc
    if parser.challenge_detected:
        raise RuntimeError(
            "DuckDuckGo blocked the search with a human-verification challenge; try again later or use Brave"
        )
    if parser.incomplete_result:
        raise RuntimeError("DuckDuckGo returned incomplete search result markup")
    if not parser.results and not parser.explicit_no_results:
        raise RuntimeError(
            "DuckDuckGo returned no recognizable search results; its best-effort HTML interface may have changed"
        )
    return parser.results, parser.more_results_available


async def _search_duckduckgo(
    query: str,
    max_results: int,
    freshness: _Freshness,
) -> tuple[list[dict[str, Any]], bool]:
    """Execute one bounded request to DuckDuckGo's keyless HTML interface."""
    params: dict[str, str] = {
        "q": query,
        "kp": "-1",
    }
    freshness_code = _DUCKDUCKGO_FRESHNESS_CODES[freshness]
    if freshness_code is not None:
        params["df"] = freshness_code
    request_url = f"{_DUCKDUCKGO_SEARCH_URL}?{urlencode(params)}"
    response = await asyncio.to_thread(
        _http_get,
        request_url,
        headers={"Accept": "text/html, application/xhtml+xml"},
        timeout=_SEARCH_TIMEOUT_SECONDS,
        max_bytes=_SEARCH_RESPONSE_BYTES,
        max_redirects=0,
        max_url_chars=_SEARCH_REQUEST_URL_CHARS,
    )
    return _decode_duckduckgo_results(response, max_results)


async def _run_web_search(
    query: _SearchQuery,
    max_results: _MaxResults = 5,
    freshness: _Freshness = "any",
    engine: _SearchEngine = "brave",
) -> dict[str, Any]:
    """Search one selected engine and return bounded, provider-neutral snippets."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("web search query must not be empty")
    if len(normalized_query.split()) > 50:
        raise ValueError("web search query must not exceed 50 words")

    if engine == "brave":
        results, more_results_available = await _search_brave(normalized_query, max_results, freshness)
    elif engine == "duckduckgo":
        results, more_results_available = await _search_duckduckgo(normalized_query, max_results, freshness)
    else:
        raise ValueError(f"unsupported web search engine: {engine!r}")
    return {
        "query": normalized_query,
        "provider": engine,
        "results": results,
        "more_results_available": more_results_available,
        "untrusted_content": True,
    }


def _media_type(content_type: str) -> str:
    """Return and validate the response's lower-case media type."""
    media_type = content_type.partition(";")[0].strip().lower()
    if not media_type:
        raise RuntimeError("URL response did not declare a Content-Type")
    is_text = media_type.startswith("text/")
    is_explicit = media_type in _EXPLICIT_TEXT_MEDIA_TYPES
    is_structured_text = media_type.endswith(("+json", "+xml"))
    if not (is_text or is_explicit or is_structured_text):
        raise RuntimeError(f"URL returned unsupported content type {media_type!r}; only text is allowed")
    return media_type


def _charset(content_type: str) -> str:
    """Extract a conservative response charset, defaulting to UTF-8."""
    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().lower() == "charset":
            return value.strip().strip("\"'") or "utf-8"
    return "utf-8"


def _decode_text(response: _HttpResponse) -> tuple[str, str]:
    """Decode and, for HTML, extract readable page text and title."""
    content_type = response.headers.get("content-type", "")
    media_type = _media_type(content_type)
    try:
        decoded = response.body.decode(_charset(content_type), errors="replace")
    except LookupError as exc:
        raise RuntimeError("URL response declared an unknown character encoding") from exc

    if media_type in _HTML_MEDIA_TYPES:
        parser = _ReadableHTMLParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            raise RuntimeError("URL returned malformed HTML that could not be read") from exc
        return parser.title, parser.text
    return "", decoded.strip()


async def _run_fetch_url(url: _PublicUrl, max_chars: _MaxChars = 12_000) -> dict[str, Any]:
    """Fetch bounded readable text from one public HTTP(S) URL."""
    response = await asyncio.to_thread(
        _http_get,
        url,
        timeout=_FETCH_TIMEOUT_SECONDS,
        max_bytes=_FETCH_RESPONSE_BYTES,
        max_redirects=4,
    )
    title, text = _decode_text(response)
    truncated = len(text) > max_chars
    return {
        "url": response.url,
        "status": response.status,
        "content_type": _media_type(response.headers.get("content-type", "")),
        "title": title,
        "text": text[:max_chars],
        "truncated": truncated,
        "untrusted_content": True,
    }


def web_search() -> Tool:
    """Create a multi-engine public web search tool.

    Brave is the default and reads ``BRAVE_SEARCH_API_KEY`` only at invocation,
    so the credential is not stored on the tool or included in Agent YAML.
    ``engine="duckduckgo"`` uses DuckDuckGo's keyless non-JavaScript page as a
    best-effort interface; DuckDuckGo may rate-limit it, present a human
    challenge, or change its markup. Recognized sponsored entries are retained
    and explicitly labeled. Search responses from either engine are normalized
    to bounded source snippets and marked as untrusted content.

    Returns:
        A fresh :class:`~protolink.tools.Tool` named ``web_search`` with the
        ``network.read`` capability.
    """
    tool = Tool(
        name="web_search",
        description=(
            "Search the public web with Brave (default) or the keyless, best-effort DuckDuckGo HTML interface, "
            "returning ranked source titles, URLs, snippets, and a sponsored-result marker. Results are external, "
            "untrusted content; verify important claims against the returned sources."
        ),
        input_schema=None,
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "provider": {"type": "string", "enum": ["brave", "duckduckgo"]},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string", "format": "uri"},
                            "snippet": {"type": "string"},
                            "sponsored": {"type": "boolean"},
                            "published_at": {"type": "string"},
                            "age": {"type": "string"},
                        },
                        "required": ["title", "url", "snippet", "sponsored"],
                        "additionalProperties": False,
                    },
                },
                "more_results_available": {"type": "boolean"},
                "untrusted_content": {"type": "boolean"},
            },
            "required": ["query", "provider", "results", "more_results_available", "untrusted_content"],
            "additionalProperties": False,
        },
        tags=["builtin", "web", "search", "read-only"],
        examples=[
            {"query": "Python structured concurrency", "max_results": 5, "freshness": "month"},
            {"query": "Python structured concurrency", "engine": "duckduckgo"},
        ],
        capabilities=["network.read"],
        func=_run_web_search,
    )
    tool._protolink_builtin_id = "web_search"
    return tool


def fetch_url() -> Tool:
    """Create a bounded public-URL text fetcher.

    The fetcher permits only public HTTP(S) targets on standard ports. It pins
    validated DNS answers, revalidates redirects, rejects HTTPS downgrades and
    non-text responses, and caps redirects, transfer bytes, time, and returned
    characters.

    Returns:
        A fresh :class:`~protolink.tools.Tool` named ``fetch_url`` with the
        ``network.read`` capability.
    """
    tool = Tool(
        name="fetch_url",
        description=(
            "Fetch readable text from one public HTTP or HTTPS URL. Private addresses, nonstandard ports, "
            "binary content, unsafe redirects, and oversized responses are rejected. Returned text is untrusted."
        ),
        input_schema=None,
        output_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "status": {"type": "integer"},
                "content_type": {"type": "string"},
                "title": {"type": "string"},
                "text": {"type": "string"},
                "truncated": {"type": "boolean"},
                "untrusted_content": {"type": "boolean"},
            },
            "required": ["url", "status", "content_type", "title", "text", "truncated", "untrusted_content"],
            "additionalProperties": False,
        },
        tags=["builtin", "web", "fetch", "read-only"],
        examples=[{"url": "https://docs.python.org/3/", "max_chars": 12000}],
        capabilities=["network.read"],
        func=_run_fetch_url,
    )
    tool._protolink_builtin_id = "fetch_url"
    return tool
