"""Command-line utilities for bootstrapping Protolink projects.

The CLI intentionally starts small and conservative. It exposes deterministic
scaffolding commands that generate runnable source files without requiring a
network service, registry, or LLM credentials. This keeps the first developer
experience fast while preserving Protolink's standard runtime APIs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from protolink.templates import TEMPLATES


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser and command tree.

    The parser is kept separate from ``main()`` so tests can exercise command
    construction and command execution independently. Subcommands are explicit
    instead of inferred dynamically, which keeps the public CLI stable and
    makes generated help output predictable.
    """
    parser = argparse.ArgumentParser(
        prog="protolink",
        description="Developer utilities for Protolink projects.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create starter files.")
    init_subparsers = init_parser.add_subparsers(dest="kind", required=True)

    agent_parser = init_subparsers.add_parser("agent", help="Create a one-file starter agent.")
    agent_parser.add_argument(
        "path",
        nargs="?",
        default="agent.py",
        help="Output file path. Defaults to ./agent.py.",
    )
    agent_parser.add_argument(
        "--template",
        choices=sorted(TEMPLATES),
        default="basic",
        help="Starter template to use.",
    )
    agent_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    return parser


def _init_agent(path: str, *, template: str, force: bool) -> int:
    """Create a starter agent source file from a bundled template.

    Args:
        path: Destination file path. Parent directories are created when
            needed.
        template: Key in ``protolink.templates.TEMPLATES`` identifying the
            starter variant to write.
        force: Whether to overwrite an existing destination file.

    Returns:
        Process-style exit code: ``0`` on success and ``1`` when overwrite
        protection prevents writing the file.
    """
    output_path = Path(path).expanduser()
    if output_path.exists() and not force:
        print(f"Refusing to overwrite existing file: {output_path}", file=sys.stderr)
        print("Use --force to overwrite it.", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(TEMPLATES[template], encoding="utf-8")
    print(f"Created {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the Protolink CLI.

    Args:
        argv: Optional argument vector for tests and embedding. When ``None``,
            ``argparse`` reads from ``sys.argv``.

    Returns:
        Integer exit code suitable for ``raise SystemExit(main())``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init" and args.kind == "agent":
        return _init_agent(args.path, template=args.template, force=args.force)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
