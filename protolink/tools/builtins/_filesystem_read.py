"""Bounded read operations sharing FilesystemResource's descriptor-based roots."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import stat
from collections.abc import Generator
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from protolink.tools.builtins._integration import integration_tool
from protolink.tools.prepared import PreparedTool

if TYPE_CHECKING:
    from protolink.tools.builtins.filesystem import FilesystemResource

_Limit = Annotated[int, Field(ge=1, le=1000)]
_Offset = Annotated[int, Field(ge=0)]
_Chars = Annotated[int, Field(ge=1, le=20000)]


def _walk(
    fd: int, path: Path, state: dict[str, Any], depth: int = 0, *, recursive: bool
) -> Generator[tuple[Path, str], None, None]:
    """Walk without resolving directory symlinks or collecting an unbounded listing."""
    with os.scandir(fd) as entries:
        for entry in entries:
            state["scanned"] += 1
            if state["scanned"] > 10000:
                state["truncated"] = True
                return
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError:
                state["skipped"] += 1
                continue
            kind = "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "other"
            child_path = path / entry.name
            yield child_path, kind
            if recursive and kind == "directory":
                if depth >= 19:
                    state["truncated"] = True
                    continue
                try:
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError:
                    state["skipped"] += 1
                    continue
                try:
                    yield from _walk(child, child_path, state, depth + 1, recursive=recursive)
                finally:
                    os.close(child)
                if state["scanned"] > 10000:
                    return


def reading_tools(resource: FilesystemResource) -> tuple[PreparedTool, ...]:
    """Create read-only tools for one already-configured file resource."""

    def text(path: str) -> str:
        snapshot = resource.read(path)
        if snapshot.data is None:
            raise FileNotFoundError(path)
        if b"\x00" in snapshot.data:
            raise ValueError("File contains binary content; use document extraction for supported formats")
        return snapshot.data.decode("utf-8")

    async def read_file(path: str, offset: _Offset = 0, max_chars: _Chars = 20000) -> dict[str, Any]:
        """Read bounded UTF-8 text. Continue with next_offset (characters) while the file remains unchanged."""
        content = await asyncio.to_thread(text, path)
        end = min(offset + max_chars, len(content))
        return {"path": path, "content": content[offset:end], "next_offset": end if end < len(content) else None}

    def scan(
        path: str, pattern: str, max_results: int, query: str | None, *, recursive: bool, case_sensitive: bool
    ) -> dict[str, Any]:
        state: dict[str, Any] = {"scanned": 0, "skipped": 0, "truncated": False}
        items: list[dict[str, Any]] = []
        read_bytes = 0
        needle = query if case_sensitive or query is None else query.casefold()
        with (
            resource.directory(path) as (fd, resolved),
            closing(_walk(fd, resolved, state, recursive=recursive)) as walk,
        ):
            for file_path, kind in walk:
                if not fnmatch.fnmatchcase(file_path.name, pattern):
                    continue
                if query is None:
                    if len(items) == max_results:
                        state["truncated"] = True
                        break
                    items.append({"path": str(file_path), "type": kind})
                    continue
                if kind != "file":
                    continue
                remaining = 32 * 1024 * 1024 - read_bytes
                if remaining <= 0:
                    state["truncated"] = True
                    break
                try:
                    snapshot = resource.read(str(file_path), max_bytes=remaining)
                    raw = snapshot.data or b""
                    read_bytes += len(raw)
                    if b"\x00" in raw:
                        raise ValueError("binary file")
                    content = raw.decode("utf-8")
                except (OSError, ValueError):
                    state["skipped"] += 1
                    continue
                for line_number, line in enumerate(content.splitlines(), 1):
                    compared = line if case_sensitive else line.casefold()
                    if needle is not None and needle in compared:
                        if len(items) == max_results:
                            state["truncated"] = True
                            break
                        items.append(
                            {
                                "path": str(file_path),
                                "line": line_number,
                                "text": line[:500],
                                "text_truncated": len(line) > 500,
                            }
                        )
                if state["truncated"]:
                    break
        return {"items": items, **state}

    async def list_files(
        path: str, *, pattern: str = "*", recursive: bool = False, max_results: _Limit = 100
    ) -> dict[str, Any]:
        """List bounded entries matching a filename glob, optionally recursively, without following symlinks."""
        return await asyncio.to_thread(scan, path, pattern, max_results, None, recursive=recursive, case_sensitive=True)

    async def search_files(
        path: str, query: str, *, pattern: str = "*", case_sensitive: bool = False, max_results: _Limit = 100
    ) -> dict[str, Any]:
        """Recursively search literal text in UTF-8 files; return paths, line numbers, and bounded matching lines."""
        return await asyncio.to_thread(
            scan, path, pattern, max_results, query, recursive=True, case_sensitive=case_sensitive
        )

    def validate(arguments: dict[str, Any]) -> None:
        resource._target(arguments["path"], allow_root=True)
        if "query" in arguments and not arguments["query"]:
            raise ValueError("Search query must not be empty")

    return tuple(
        integration_tool(
            function,
            capability="filesystem.read",
            target="configured filesystem roots",
            timeout_seconds=30,
            validate=validate,
        )
        for function in (read_file, list_files, search_files)
    )
