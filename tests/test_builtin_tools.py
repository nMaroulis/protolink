"""Safety and public-contract tests for Protolink's opt-in built-in tools."""

from __future__ import annotations

import importlib
import io
import json
import socket
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from protolink import ActionDeniedError, Agent, AgentCard, AgentSkill, CapabilityPolicy
from protolink.tools import Tool, calculator, current_datetime, fetch_url, web_search

calculator_module = importlib.import_module("protolink.tools.builtins.calculator")
clock_module = importlib.import_module("protolink.tools.builtins.clock")
network_module = importlib.import_module("protolink.tools.builtins._network")
web_module = importlib.import_module("protolink.tools.builtins.web")


BUILTIN_FACTORIES: tuple[tuple[Callable[[], Tool], str, tuple[str, ...]], ...] = (
    (calculator, "calculator", ()),
    (current_datetime, "current_datetime", ()),
    (web_search, "web_search", ("network.read",)),
    (fetch_url, "fetch_url", ("network.read",)),
)


@pytest.mark.parametrize(("factory", "name", "capabilities"), BUILTIN_FACTORIES)
def test_builtin_factories_return_fresh_tools_with_complete_metadata(
    factory: Callable[[], Tool],
    name: str,
    capabilities: tuple[str, ...],
) -> None:
    """Every public factory should return an independent ordinary Tool."""
    first = factory()
    second = factory()

    assert isinstance(first, Tool)
    assert isinstance(second, Tool)
    assert first is not second
    assert first.name == name
    assert first.description.strip()
    assert first.tags is not second.tags
    assert "builtin" in (first.tags or [])
    assert tuple(first.capabilities or ()) == capabilities
    assert first.examples
    assert first.input_schema == second.input_schema
    assert first.output_schema == second.output_schema
    assert first.input_schema is not second.input_schema
    assert first.input_schema is not None
    assert first.input_schema["type"] == "object"
    assert first.input_schema["additionalProperties"] is False
    assert isinstance(first.output_schema, dict)
    assert first.func.__module__.startswith("protolink.tools.builtins.")


@pytest.mark.asyncio
async def test_calculator_evaluates_only_supported_arithmetic() -> None:
    tool = calculator()

    result = await tool(expression="(2 + 3) * 4 ** 2 - 5 / 2")

    assert result == {"expression": "(2 + 3) * 4 ** 2 - 5 / 2", "result": 77.5}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "open('/etc/passwd').read()",
        "value + 1",
        "True + 1",
        "2 ** 1000000",
        "1e309",
        "1 + " * 600 + "1",
    ],
)
async def test_calculator_rejects_code_and_resource_exhaustion(expression: str) -> None:
    with pytest.raises(ValueError):
        await calculator()(expression=expression)


@pytest.mark.asyncio
async def test_calculator_reports_division_by_zero() -> None:
    with pytest.raises(ValueError, match="zero"):
        await calculator()(expression="10 / 0")


@pytest.mark.asyncio
async def test_current_datetime_defaults_to_aware_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 7, 15, 10, 11, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(clock_module, "_now", lambda zone: fixed.astimezone(zone))

    result = await current_datetime()()

    assert result["timezone"] == "UTC"
    assert result["iso8601"] == "2026-07-15T10:11:12+00:00"
    assert result["utc_offset"] == "+00:00"
    assert result["unix_timestamp"] == fixed.timestamp()


@pytest.mark.asyncio
async def test_current_datetime_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        await current_datetime()(timezone="Mars/Olympus_Mons")


@pytest.mark.asyncio
async def test_current_datetime_utc_does_not_require_host_timezone_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = datetime(2026, 7, 15, 10, 11, 12, tzinfo=timezone.utc)

    def fail_zone_lookup(name: str) -> Any:
        raise clock_module.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(clock_module, "ZoneInfo", fail_zone_lookup)
    monkeypatch.setattr(clock_module, "_now", lambda zone: fixed.astimezone(zone))

    result = await current_datetime()()

    assert result["timezone"] == "UTC"
    assert result["iso8601"] == "2026-07-15T10:11:12+00:00"


@pytest.mark.asyncio
async def test_web_search_requires_api_key_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("network must not run without credentials")

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr(web_module, "_http_get", fail_if_called)

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await web_search()(query="safe agent runtimes")

    assert called is False


@pytest.mark.asyncio
async def test_web_search_normalizes_mocked_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    payload = {
        "web": {
            "results": [
                {
                    "title": "ProtoLink documentation",
                    "url": "https://example.com/protolink",
                    "description": "Typed agent tools and runtime policy.",
                    "age": "2 hours ago",
                    "provider_private": "must not escape",
                },
                {
                    "title": "Agent runtime guide",
                    "url": "https://example.org/guide",
                    "description": "A second result.",
                },
            ]
        },
        "raw_provider_metadata": {"secret": True},
    }

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=json.dumps(payload).encode("utf-8"),
        )

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-search-key")
    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await web_search()(query="safe agent runtimes", max_results=1, freshness="week")

    assert result["query"] == "safe agent runtimes"
    assert result["provider"] == "brave"
    assert result["untrusted_content"] is True
    assert result["results"] == [
        {
            "title": "ProtoLink documentation",
            "url": "https://example.com/protolink",
            "snippet": "Typed agent tools and runtime policy.",
            "sponsored": False,
            "age": "2 hours ago",
        }
    ]
    assert result["more_results_available"] is False
    assert result["untrusted_content"] is True
    assert "raw_provider_metadata" not in result
    assert captured["headers"]["X-Subscription-Token"] == "test-search-key"
    assert "test-search-key" not in captured["url"]


def test_web_search_schema_exposes_deterministic_engine_selection() -> None:
    tool = web_search()

    assert tool.input_schema is not None
    assert tool.input_schema["properties"]["engine"] == {
        "description": "Search provider: Brave by default, or keyless best-effort DuckDuckGo HTML search.",
        "enum": ["brave", "duckduckgo"],
        "type": "string",
        "default": "brave",
    }
    assert tool.output_schema["properties"]["provider"]["enum"] == ["brave", "duckduckgo"]
    result_schema = tool.output_schema["properties"]["results"]["items"]
    assert "sponsored" in result_schema["required"]
    assert tool.examples[-1]["engine"] == "duckduckgo"


@pytest.mark.asyncio
async def test_web_search_rejects_unknown_engine_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("invalid engine must fail schema validation")

    monkeypatch.setattr(web_module, "_http_get", fail_if_called)

    with pytest.raises(ValueError):
        await web_search()(query="safe agent runtimes", engine="bing")

    assert called is False


@pytest.mark.asyncio
async def test_duckduckgo_search_is_keyless_and_normalizes_current_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    body = b"""
        <html><body>
          <!-- Web results are present -->
          <div class="result results_links web-result">
            <div class="result__body">
              <h2><a class="result__a"
                href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs%3Ftopic%3Dagents&amp;rut=opaque">
                Proto<b>Link</b> &amp; agents
              </a></h2>
              <a class="result__snippet" href="#ignored">
                Typed <b>agent</b> tools &amp; runtime policy.
              </a>
            </div>
          </div>
          <input class="btn btn--alt" type="submit" value="Next" />
        </body></html>
    """

    def fail_brave_key() -> str:
        raise AssertionError("DuckDuckGo must not read the Brave credential")

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        )

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setattr(web_module, "_brave_api_key", fail_brave_key)
    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await web_search()(
        query="  safe agent runtimes  ",
        max_results=5,
        freshness="week",
        engine="duckduckgo",
    )

    assert result == {
        "query": "safe agent runtimes",
        "provider": "duckduckgo",
        "results": [
            {
                "title": "ProtoLink & agents",
                "url": "https://example.com/docs?topic=agents",
                "snippet": "Typed agent tools & runtime policy.",
                "sponsored": False,
            }
        ],
        "more_results_available": True,
        "untrusted_content": True,
    }
    query_params = parse_qs(urlsplit(captured["url"]).query)
    assert query_params == {"q": ["safe agent runtimes"], "kp": ["-1"], "df": ["w"]}
    assert captured["headers"] == {"Accept": "text/html, application/xhtml+xml"}
    assert captured["timeout"] == web_module._SEARCH_TIMEOUT_SECONDS
    assert captured["max_bytes"] == web_module._SEARCH_RESPONSE_BYTES
    assert captured["max_redirects"] == 0
    assert captured["max_url_chars"] == web_module._SEARCH_REQUEST_URL_CHARS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("freshness", "expected_code"),
    [
        ("any", None),
        ("day", "d"),
        ("week", "w"),
        ("month", "m"),
        ("year", "y"),
    ],
)
async def test_duckduckgo_search_maps_every_freshness_filter(
    freshness: str,
    expected_code: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_url = ""

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        nonlocal captured_url
        del kwargs
        captured_url = url
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=b'<html><div class="no-results">No results.</div></html>',
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await web_search()(query="no matching page", freshness=freshness, engine="duckduckgo")

    assert result["results"] == []
    params = parse_qs(urlsplit(captured_url).query)
    if expected_code is None:
        assert "df" not in params
    else:
        assert params["df"] == [expected_code]


@pytest.mark.asyncio
async def test_duckduckgo_search_preserves_labeled_ads_and_marks_withheld_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"""
        <html><body>
          <div class="result web-result result--ad">
            <a class="result__a"
              href="//duckduckgo.com/y.js?ad_domain=ads.example&amp;uddg=https%3A%2F%2Fads.example%2Fsponsored">
              Sponsored
            </a>
            <a class="result__snippet">Advertisement</a>
          </div>
          <div class="result web-result">
            <a class="result__a" href="https://first.example/a#fragment">First result</a>
            <a class="result__snippet">First snippet</a>
          </div>
          <div class="result web-result">
            <a class="result__a" href="https://second.example/b">Second result</a>
            <a class="result__snippet">Second snippet</a>
          </div>
        </body></html>
    """

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await web_search()(query="results", max_results=2, engine="duckduckgo")

    assert result["results"] == [
        {
            "title": "Sponsored",
            "url": ("https://duckduckgo.com/y.js?ad_domain=ads.example&uddg=https%3A%2F%2Fads.example%2Fsponsored"),
            "snippet": "Advertisement",
            "sponsored": True,
        },
        {
            "title": "First result",
            "url": "https://first.example/a",
            "snippet": "First snippet",
            "sponsored": False,
        },
    ]
    assert result["more_results_available"] is True


@pytest.mark.parametrize(
    "url",
    [
        "//duckduckgo.com/l/?rut=missing-destination",
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&uddg=https%3A%2F%2Fevil.example",
        "//duckduckgo.com/l/?uddg=https%253A%252F%252Fexample.com",
        "//duckduckgo.com/l/?uddg=javascript%3Aalert%281%29",
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fuser%3Apassword%40example.com%2Fprivate",
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fline%0Abreak",
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&a=1&b=2&c=3&d=4&e=5&f=6&g=7&h=8",
    ],
)
def test_duckduckgo_redirect_unwrapper_rejects_hostile_destinations(url: str) -> None:
    assert web_module._duckduckgo_result_url(url) == ""


def test_duckduckgo_result_url_accepts_safe_direct_and_wrapped_urls() -> None:
    assert web_module._duckduckgo_result_url("https://example.com/direct#section") == "https://example.com/direct"
    assert (
        web_module._duckduckgo_result_url(
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fwrapped%3Fx%3D1&rut=opaque"
        )
        == "https://example.org/wrapped?x=1"
    )
    assert web_module._duckduckgo_result_url("x" * 4097) == ""


def test_duckduckgo_parser_bounds_provider_text() -> None:
    parser = web_module._DuckDuckGoHTMLParser(max_results=1)
    parser.feed(
        '<div class="result web-result">'
        f'<a class="result__a" href="https://example.com">{"t" * 800}</a>'
        f'<a class="result__snippet">{"s" * 3000}</a>'
        "</div>"
    )
    parser.close()
    parser.finish()

    assert len(parser.results[0]["title"]) == 500
    assert len(parser.results[0]["snippet"]) == 2000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "challenge_marker",
    [
        "<form id='challenge-form'></form>",
        '<div class="anomaly-modal"></div>',
        '<form action="/anomaly.js"></form>',
    ],
)
async def test_duckduckgo_search_surfaces_human_verification_challenges(
    challenge_marker: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=f"<html>{challenge_marker}</html>".encode(),
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    with pytest.raises(RuntimeError, match="human-verification"):
        await web_search()(query="agent runtimes", engine="duckduckgo")


@pytest.mark.asyncio
async def test_duckduckgo_challenge_words_in_query_and_results_do_not_false_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"""
        <html>
          <head><title>anomaly.js challenge-form at DuckDuckGo</title></head>
          <body>
            <input value="bots use DuckDuckGo too" />
            <div class="result web-result">
              <a class="result__a" href="https://example.com/challenge-form">anomaly.js reference</a>
              <a class="result__snippet">Article about the anomaly-modal and challenge-form markup.</a>
            </div>
          </body>
        </html>
    """

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await web_search()(query="anomaly.js challenge-form", engine="duckduckgo")

    assert result["results"][0]["title"] == "anomaly.js reference"
    assert result["results"][0]["sponsored"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b"<html><body>unexpected page</body></html>", "no recognizable"),
        (
            b'<html><div class="result web-result"><a class="result__a" href="https://example.com">open',
            "incomplete",
        ),
    ],
)
async def test_duckduckgo_search_rejects_markup_drift(
    body: bytes,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    with pytest.raises(RuntimeError, match=error):
        await web_search()(query="agent runtimes", engine="duckduckgo")


@pytest.mark.asyncio
async def test_duckduckgo_search_requires_html_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "application/json"},
            body=b"{}",
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    with pytest.raises(RuntimeError, match="expected HTML"):
        await web_search()(query="agent runtimes", engine="duckduckgo")


@pytest.mark.asyncio
async def test_web_search_rejects_result_limit_outside_contract() -> None:
    with pytest.raises(ValueError):
        await web_search()(query="test", max_results=11)


@pytest.mark.asyncio
async def test_web_search_supports_max_length_unicode_query_after_percent_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_getaddrinfo(hostname: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        del hostname, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        network_module._validate_and_resolve(url, max_url_chars=kwargs["max_url_chars"])
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "application/json"},
            body=b'{"web":{"results":[]}}',
        )

    monkeypatch.setattr(network_module.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(web_module, "_http_get", fake_http_get)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-search-key")

    result = await web_search()(query=chr(0x1F600) * 400)

    assert result["results"] == []
    assert len(captured["url"]) > 2048
    assert captured["max_url_chars"] == web_module._SEARCH_REQUEST_URL_CHARS


@pytest.mark.parametrize("error", [RecursionError("nested JSON"), ValueError("integer digit limit")])
def test_web_search_wraps_json_resource_limit_errors(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_json_loads(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise error

    monkeypatch.setattr(web_module.json, "loads", fail_json_loads)
    response = network_module._response_for_tests(
        url="https://api.search.brave.com/res/v1/web/search",
        status=200,
        headers={"content-type": "application/json"},
        body=b"{}",
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        web_module._decode_json(response)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/space here",
        "https://example.com/line\nbreak",
        "https://example.com/carriage\rreturn",
        "https://example.com/tab\tvalue",
        "https://example.com/back\\slash",
        "https://./empty-host",
    ],
)
def test_web_search_rejects_hostile_provider_result_urls(url: str) -> None:
    assert web_module._valid_result_url(url) == ""


def test_web_search_normalizes_provider_result_url() -> None:
    assert (
        web_module._valid_result_url("HTTPS://EXAMPLE.COM/docs?q=tools#fragment") == "https://example.com/docs?q=tools"
    )


@pytest.mark.asyncio
async def test_fetch_url_extracts_bounded_plain_text_from_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"""
        <html>
          <head>
            <title>Example page</title>
            <style>.hidden { display: none; }</style>
            <script>ignoreThisInstruction()</script>
          </head>
          <body><h1>Hello</h1><p>World &amp; friends.</p></body>
        </html>
    """

    def fake_http_get(url: str, **kwargs: Any) -> Any:
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await fetch_url()(url="https://93.184.216.34/page")

    assert result["url"] == "https://93.184.216.34/page"
    assert result["content_type"] == "text/html"
    assert result["title"] == "Example page"
    assert "Hello" in result["text"]
    assert "World & friends." in result["text"]
    assert "ignoreThisInstruction" not in result["text"]
    assert "display: none" not in result["text"]
    assert result["truncated"] is False
    assert result["untrusted_content"] is True
    assert result["untrusted_content"] is True


@pytest.mark.asyncio
async def test_fetch_url_truncates_text_to_requested_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_http_get(url: str, **kwargs: Any) -> Any:
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/plain; charset=utf-8"},
            body=("word " * 100).encode(),
        )

    monkeypatch.setattr(web_module, "_http_get", fake_http_get)

    result = await fetch_url()(url="https://93.184.216.34/long", max_chars=100)

    assert len(result["text"]) <= 100
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_fetch_url_rejects_private_address_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("private address must be rejected before HTTP")

    monkeypatch.setattr(
        network_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80))],
    )
    monkeypatch.setattr(network_module, "_request_once", fail_if_called)

    with pytest.raises(ValueError, match="public"):
        await fetch_url()(url="http://127.0.0.1/private")

    assert called is False


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "224.0.0.1",
        "192.0.0.8",
        "::1",
        "ff02::1",
        "fec0::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::",
        "2002:a9fe:a9fe::",
        "2002:a00:1::",
    ],
)
def test_network_rejects_every_non_public_address_class(address: str) -> None:
    with pytest.raises(ValueError, match="non-public"):
        network_module._public_ip(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "2001:4860:4860::8888"])
def test_network_accepts_public_addresses(address: str) -> None:
    assert network_module._public_ip(address) == address


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("Host ", "example.com"),
        ("Transfer-Encoding ", "chunked"),
        ("Bad Header", "value"),
        ("X-Test", "safe\r\nHost: internal"),
        ("X-Test", "unsafe\x00value"),
    ],
)
def test_network_rejects_invalid_or_disguised_request_headers(name: str, value: str) -> None:
    with pytest.raises(ValueError, match="header"):
        network_module._request_headers({name: value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@93.184.216.34/private",
        "https://93.184.216.34:8443/nonstandard",
    ],
)
async def test_fetch_url_rejects_unsafe_url_forms_before_network(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("unsafe URL must be rejected before HTTP")

    monkeypatch.setattr(network_module, "_request_once", fail_if_called)

    with pytest.raises(ValueError):
        await fetch_url()(url=url)

    assert called is False


@pytest.mark.asyncio
async def test_fetch_url_rejects_hostname_with_mixed_public_and_private_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", 443)),
        ]

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("mixed DNS answer must be rejected before HTTP")

    monkeypatch.setattr(network_module.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(network_module, "_request_once", fail_if_called)

    with pytest.raises(ValueError, match="public"):
        await fetch_url()(url="https://mixed.example/resource")

    assert called is False


@pytest.mark.parametrize("unsafe_address", ["224.0.0.1", "ff02::1", "fec0::1"])
@pytest.mark.asyncio
async def test_fetch_url_rejects_nonpublic_dns_answer_classes(
    unsafe_address: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (unsafe_address, 443))]

    monkeypatch.setattr(network_module.socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="non-public"):
        await fetch_url()(url="https://unsafe-dns.example/resource")


@pytest.mark.asyncio
async def test_fetch_url_rejects_https_to_http_redirect_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_request_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return network_module._response_for_tests(
            url="https://93.184.216.34/secure",
            status=302,
            headers={"location": "http://93.184.216.34/plain"},
            body=b"",
        )

    monkeypatch.setattr(network_module, "_request_once", fake_request_once)

    with pytest.raises(ValueError, match="downgrade"):
        await fetch_url()(url="https://93.184.216.34/secure")

    assert calls == 1


@pytest.mark.asyncio
async def test_network_policy_denies_fetch_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("denied tool must not reach HTTP")

    monkeypatch.setattr(web_module, "_http_get", fail_if_called)
    agent = Agent(
        AgentCard(
            name="builtin-policy-agent",
            description="Exercises built-in policy enforcement.",
            url="runtime://builtin-policy-agent",
        ),
        transport="runtime",
        policy=CapabilityPolicy({"network.read": "deny"}),
        verbosity=0,
    )
    agent.add_tool(fetch_url())

    with pytest.raises(ActionDeniedError):
        await agent.call_tool("fetch_url", url="https://93.184.216.34/resource")

    assert called is False


def test_network_request_has_hard_response_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    released = threading.Event()

    class FakeSocket:
        def shutdown(self, how: int) -> None:
            del how
            released.set()

        def settimeout(self, timeout: float) -> None:
            del timeout

    class FakeResponse:
        status = 200

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "text/plain")]

        def read(self, amount: int) -> bytes:
            del amount
            assert released.wait(1.0)
            raise OSError("deadline closed the socket")

    class FakeConnection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.sock = FakeSocket()

        def connect(self) -> None:
            return None

        def request(self, *args: Any, **kwargs: Any) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            released.set()

    monkeypatch.setattr(network_module.http.client, "HTTPConnection", FakeConnection)
    resolved = network_module._ResolvedUrl(
        url="http://93.184.216.34/slow",
        scheme="http",
        hostname="93.184.216.34",
        port=80,
        target="/slow",
        host_header="93.184.216.34",
        connect_ips=("93.184.216.34",),
    )

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="deadline"):
        network_module._request_once(resolved, headers=None, timeout=0.02, max_bytes=1024)

    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    ("wire_body", "expected_body", "error_match"),
    [
        pytest.param(
            b"8\r\nfallback\r\n7\r\n worked\r\n0\r\n\r\n",
            b"fallback worked",
            None,
            id="valid-chunking",
        ),
        pytest.param(
            b"-1\r\n" + (b"x" * 100_000),
            None,
            "chunk size",
            id="negative-chunk-size",
        ),
    ],
)
def test_network_decodes_chunked_body_without_unbounded_reads(
    wire_body: bytes,
    expected_body: bytes | None,
    error_match: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.BytesIO(wire_body)

    class FakeSocket:
        def shutdown(self, how: int) -> None:
            del how

        def settimeout(self, timeout: float) -> None:
            del timeout

    class FakeResponse:
        status = 200
        chunked = True
        fp = stream

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "text/plain"), ("Transfer-Encoding", "chunked")]

    class FakeConnection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.sock = FakeSocket()

        def connect(self) -> None:
            return None

        def request(self, *args: Any, **kwargs: Any) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(network_module.http.client, "HTTPConnection", FakeConnection)
    resolved = network_module._ResolvedUrl(
        url="http://93.184.216.34/chunked",
        scheme="http",
        hostname="93.184.216.34",
        port=80,
        target="/chunked",
        host_header="93.184.216.34",
        connect_ips=("93.184.216.34",),
    )

    if error_match is not None:
        with pytest.raises(RuntimeError, match=error_match):
            network_module._request_once(resolved, headers=None, timeout=1.0, max_bytes=1024)
        assert stream.tell() < 100
    else:
        response = network_module._request_once(resolved, headers=None, timeout=1.0, max_bytes=1024)
        assert response.body == expected_body


def test_network_falls_back_across_prevalidated_addresses_under_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_calls: list[tuple[str, int]] = []
    connection_attempts: list[tuple[str, float]] = []

    def fake_getaddrinfo(hostname: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        del kwargs
        resolver_calls.append((hostname, port))
        return [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2606:4700:4700::1111", port, 0, 0),
            ),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port)),
        ]

    class FakeResponse:
        status = 200

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "text/plain")]

        def read(self, amount: int) -> bytes:
            del amount
            return b"fallback worked"

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            del port
            self.host = host
            self.sock = None
            connection_attempts.append((host, timeout))

        def connect(self) -> None:
            if self.host == "2606:4700:4700::1111":
                time.sleep(0.01)
                raise OSError("IPv6 route unavailable")

        def request(self, *args: Any, **kwargs: Any) -> None:
            return None

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(network_module.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(network_module.http.client, "HTTPConnection", FakeConnection)

    response = network_module._http_get("http://fallback.example/resource", timeout=1.0)

    assert response.body == b"fallback worked"
    assert resolver_calls == [("fallback.example", 80)]
    assert [address for address, _ in connection_attempts] == [
        "2606:4700:4700::1111",
        "93.184.216.34",
    ]
    assert 0 < connection_attempts[0][1] < connection_attempts[1][1] <= 1.0


@pytest.mark.parametrize(("factory", "name", "capabilities"), BUILTIN_FACTORIES)
def test_builtin_registration_advertises_agent_skill(
    factory: Callable[[], Tool],
    name: str,
    capabilities: tuple[str, ...],
) -> None:
    agent = Agent(
        AgentCard(
            name=f"{name}-agent",
            description="Advertises one built-in tool.",
            url=f"runtime://{name}-agent",
        ),
        transport="runtime",
        verbosity=0,
    )
    tool = factory()

    agent.add_tool(tool)

    skill = next(item for item in agent.card.skills if item.id == name)
    assert skill.description == tool.description
    assert skill.input_schema == tool.input_schema
    assert skill.output_schema == tool.output_schema
    assert skill.tags == tool.tags
    assert skill.examples == tool.examples
    assert tuple(tool.capabilities or ()) == capabilities


def test_replacing_registered_tool_updates_advertised_skill() -> None:
    agent = Agent(
        AgentCard(
            name="replacement-agent",
            description="Keeps runtime tools and advertised skills aligned.",
            url="runtime://replacement-agent",
        ),
        transport="runtime",
        verbosity=0,
    )

    @agent.tool(name="calculator", description="Old calculator metadata")
    def old_calculator(expression: str) -> str:
        return expression

    replacement = calculator()
    agent.add_tool(replacement)

    assert agent.tools["calculator"] is replacement
    matching_skills = [skill for skill in agent.card.skills if skill.id == "calculator"]
    assert len(matching_skills) == 1
    assert matching_skills[0].description == replacement.description
    assert matching_skills[0].input_schema == replacement.input_schema


def test_registering_tool_preserves_predeclared_agent_skill() -> None:
    card = AgentCard(
        name="predeclared-skill-agent",
        description="Keeps curated card metadata separate from runtime wiring.",
        url="runtime://predeclared-skill-agent",
        skills=[
            AgentSkill(
                id="web_search",
                description="Curated public search description",
                tags=["curated"],
            )
        ],
    )
    agent = Agent(card, transport="runtime", skills="fixed", verbosity=0)
    tool = web_search()

    agent.add_tool(tool)

    matching_skills = [skill for skill in agent.card.skills if skill.id == "web_search"]
    assert len(matching_skills) == 1
    assert matching_skills[0].description == "Curated public search description"
    assert matching_skills[0].tags == ["curated"]
    assert agent.tools["web_search"] is tool


@pytest.mark.asyncio
async def test_builtin_tools_survive_agent_yaml_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = datetime(2026, 7, 15, 10, 11, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(clock_module, "_now", lambda zone: fixed.astimezone(zone))
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "yaml-must-not-contain-this-key")
    agent = Agent(
        AgentCard(
            name="builtin-yaml-agent",
            description="Round-trips built-in tools.",
            url="runtime://builtin-yaml-agent",
        ),
        transport="runtime",
        verbosity=0,
    )
    for factory, _, _ in BUILTIN_FACTORIES:
        agent.add_tool(factory())

    yaml_text = agent.to_yaml_string()
    restored = Agent.from_yaml_string(yaml_text)

    assert "yaml-must-not-contain-this-key" not in yaml_text
    assert "type: builtin" in yaml_text
    assert "builtin_id: web_search" in yaml_text
    assert "_run_web_search" not in yaml_text
    assert set(restored.tools) == {name for _, name, _ in BUILTIN_FACTORIES}
    for name, tool in restored.tools.items():
        assert isinstance(tool, Tool)
        assert tool.func.__module__.startswith("protolink.tools.builtins."), name
    assert await restored.call_tool("calculator", expression="6 * 7") == {
        "expression": "6 * 7",
        "result": 42,
    }
    assert (await restored.call_tool("current_datetime"))["iso8601"] == "2026-07-15T10:11:12+00:00"

    def fake_duckduckgo_get(url: str, **kwargs: Any) -> Any:
        del kwargs
        return network_module._response_for_tests(
            url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=b'<html><div class="no-results">No results.</div></html>',
        )

    monkeypatch.setattr(web_module, "_http_get", fake_duckduckgo_get)
    restored_search = await restored.call_tool(
        "web_search",
        query="round-tripped keyless search",
        engine="duckduckgo",
    )
    assert restored_search["provider"] == "duckduckgo"
    assert restored_search["results"] == []


@pytest.mark.asyncio
async def test_yaml_restore_honors_explicit_builtin_policy_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reloaded network tools must use the runtime policy supplied by the host."""
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("denied restored tool must not reach HTTP")

    monkeypatch.setattr(web_module, "_http_get", fail_if_called)
    source = Agent(
        AgentCard(
            name="serialized-policy-agent",
            description="Restores a runtime-owned network policy.",
            url="runtime://serialized-policy-agent",
        ),
        transport="runtime",
        policy=CapabilityPolicy({"network.read": "allow"}),
        verbosity=0,
    )
    source.add_tool(fetch_url())

    restored = Agent.from_yaml_string(
        source.to_yaml_string(),
        policy=CapabilityPolicy({"network.read": "deny"}),
        verbosity=0,
    )

    with pytest.raises(ActionDeniedError):
        await restored.call_tool("fetch_url", url="https://93.184.216.34/resource")

    assert called is False


@pytest.mark.asyncio
async def test_builtin_policy_survives_default_yaml_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A serialized restrictive policy must not reopen a network built-in."""
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("restored restrictive policy must prevent HTTP")

    monkeypatch.setattr(web_module, "_http_get", fail_if_called)
    source = Agent(
        AgentCard(
            name="round-trip-policy-agent",
            description="Keeps a restrictive policy across YAML.",
            url="runtime://round-trip-policy-agent",
        ),
        transport="runtime",
        policy=CapabilityPolicy(
            {"network.read": "deny"},
            default_effect="require_approval",
            name="network_boundary",
        ),
        verbosity=0,
    )
    source.add_tool(fetch_url())

    yaml_text = source.to_yaml_string()
    restored = Agent.from_yaml_string(yaml_text, verbosity=0)

    assert "type: capability" in yaml_text
    assert "network.read: deny" in yaml_text
    assert isinstance(restored.action_authorizer.policy, CapabilityPolicy)
    assert restored.action_authorizer.policy.rules == {"network.read": "deny"}
    assert restored.action_authorizer.policy.default_effect.value == "require_approval"
    assert restored.action_authorizer.policy.name == "network_boundary"
    with pytest.raises(ActionDeniedError):
        await restored.call_tool("fetch_url", url="https://93.184.216.34/resource")

    assert called is False


def test_custom_policy_is_override_only_during_agent_round_trip() -> None:
    """Serialized agents must not encode or import executable policy classes."""

    class CustomPolicy(CapabilityPolicy):
        async def evaluate(self, action: Any, context: Any) -> Any:
            raise AssertionError((action, context))

    custom_policy = CustomPolicy()
    source = Agent(
        AgentCard(
            name="custom-policy-agent",
            description="Uses an application-owned policy implementation.",
            url="runtime://custom-policy-agent",
        ),
        transport="runtime",
        policy=custom_policy,
        verbosity=0,
    )

    serialized = source.to_dict()
    restored = Agent.from_dict(serialized, policy=custom_policy, verbosity=0)

    assert "policy" not in serialized
    assert restored.action_authorizer.policy is custom_policy


@pytest.mark.asyncio
async def test_yaml_restore_honors_explicit_approval_handler_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime approval callbacks should remain injectable during reconstruction."""
    called = False
    approval_requested = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("rejected restored tool must not reach HTTP")

    async def reject_approval(request: Any, context: Any) -> bool:
        del request, context
        nonlocal approval_requested
        approval_requested = True
        return False

    monkeypatch.setattr(web_module, "_http_get", fail_if_called)
    source = Agent(
        AgentCard(
            name="serialized-approval-agent",
            description="Restores a runtime-owned approval callback.",
            url="runtime://serialized-approval-agent",
        ),
        transport="runtime",
        verbosity=0,
    )
    source.add_tool(fetch_url())

    restored = Agent.from_yaml_string(
        source.to_yaml_string(),
        policy=CapabilityPolicy({"network.read": "require_approval"}),
        approval_handler=reject_approval,
        verbosity=0,
    )

    with pytest.raises(ActionDeniedError):
        await restored.call_tool("fetch_url", url="https://93.184.216.34/resource")

    assert approval_requested is True
    assert called is False
