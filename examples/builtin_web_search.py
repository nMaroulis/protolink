"""Run ProtoLink's built-in web search through the normal Agent tool path.

DuckDuckGo is the example's default because it needs no API key. Brave remains
the built-in tool's default engine and can be selected here after exporting
``BRAVE_SEARCH_API_KEY``.

Run a keyless search:

    python examples/builtin_web_search.py "Python structured concurrency"

Run the same search with Brave:

    export BRAVE_SEARCH_API_KEY="your-key"
    python examples/builtin_web_search.py "Python structured concurrency" --engine brave

Running the script without a query prints help and performs no network request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from protolink import Agent, AgentCard, CapabilityPolicy
from protolink.tools import web_search


def build_parser() -> argparse.ArgumentParser:
    """Create the small command-line interface for the example."""
    parser = argparse.ArgumentParser(
        description="Search the public web with ProtoLink's built-in Brave or DuckDuckGo engine.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Search query. Omit it to print this help without making a network request.",
    )
    parser.add_argument(
        "--engine",
        choices=("brave", "duckduckgo"),
        default="duckduckgo",
        help="Search engine to call (default: duckduckgo, which needs no API key).",
    )
    parser.add_argument(
        "--freshness",
        choices=("any", "day", "week", "month", "year"),
        default="any",
        help="Optional result-age filter (default: any).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        choices=range(1, 11),
        default=5,
        help="Maximum normalized results from 1 to 10 (default: 5).",
    )
    return parser


async def run_search(
    query: str,
    *,
    engine: str,
    freshness: str,
    max_results: int,
) -> dict[str, Any]:
    """Register and invoke ``web_search`` with explicit network authority."""
    agent = Agent(
        AgentCard(
            name="builtin-web-search-example",
            description="Demonstrates ProtoLink's multi-engine built-in web search",
            url="runtime://builtin-web-search-example",
        ),
        transport="runtime",
        policy=CapabilityPolicy(
            {"network.read": "allow"},
            default_effect="deny",
        ),
        verbosity=0,
    )
    agent.add_tool(web_search())

    result = await agent.call_tool(
        "web_search",
        query=query,
        engine=engine,
        freshness=freshness,
        max_results=max_results,
    )
    if not isinstance(result, dict):
        raise RuntimeError("web_search returned an unexpected result")
    return result


def main() -> None:
    """Parse arguments, run one search when requested, and print JSON."""
    parser = build_parser()
    args = parser.parse_args()
    if args.query is None:
        parser.print_help()
        return

    try:
        result = asyncio.run(
            run_search(
                args.query,
                engine=args.engine,
                freshness=args.freshness,
                max_results=args.max_results,
            )
        )
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"web search failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
