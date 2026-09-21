"""Explicit-root filesystem tools with optional conflict-aware write recovery."""

from __future__ import annotations

import difflib
import hashlib
import os
import stat
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from protolink.core.actions import RunAction
from protolink.core.artifact import Artifact
from protolink.core.execution import ToolExecution
from protolink.core.part import Part
from protolink.core.resources import (
    CheckpointStore,
    ResourceChange,
    ResourceConflictError,
    ResourceRevision,
    ResourceSnapshot,
)
from protolink.core.run_context import RunContext
from protolink.tools.prepared import PreparedTool


class FilesystemResource:
    """POSIX file resources resolved beneath explicitly configured roots.

    All components beneath a configured root must be real directories/files:
    symlinks are rejected, including dangling links. Descriptor-relative I/O
    prevents redirecting a write through a swapped symlink. The root itself is
    resolved once, allowing platform aliases such as macOS /tmp. Parent inode
    identity and exact preimages are rechecked before replacement.

    This protects cooperating applications from stale previews; it is not an
    OS sandbox. Uncooperative writers can still race the final compare/rename.
    Only regular files and their bytes/mode are supported; ACLs, ownership,
    extended attributes, and timestamps are not restored. Windows is currently
    rejected because equivalent descriptor-relative guarantees are unavailable.
    """

    def __init__(self, roots: Sequence[str | Path], *, max_file_bytes: int = 8 * 1024 * 1024) -> None:
        """Resolve allowed roots without creating files or recovery records."""
        if os.name != "posix":
            raise NotImplementedError("FilesystemResource currently requires POSIX descriptor-relative file APIs")
        if not roots or isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 0:
            raise ValueError("Configure at least one allowed root and a non-negative file size limit")
        self.roots = {Path(root).absolute(): Path(root).resolve(strict=True) for root in roots}
        if any(not root.is_dir() for root in self.roots.values()):
            raise ValueError("Allowed roots must be existing directories")
        self.max_file_bytes = max_file_bytes

    def _target(self, resource_id: str, *, allow_root: bool = False) -> tuple[Path, Path]:
        path = Path(resource_id)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("File paths must be absolute and cannot contain '..'")
        for alias, root in sorted(self.roots.items(), key=lambda pair: len(pair[0].parts), reverse=True):
            for prefix in (alias, root):
                if path.is_relative_to(prefix) and (allow_root or path != prefix):
                    return root, root / path.relative_to(prefix)
        raise ValueError("File path is outside the allowed roots")

    @contextmanager
    def directory(self, resource_id: str) -> Iterator[tuple[int, Path]]:
        """Open a directory beneath a configured root without following symlinks."""
        root, path = self._target(resource_id, allow_root=True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root, flags)
        try:
            for component in path.relative_to(root).parts:
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, path
        finally:
            os.close(fd)

    @contextmanager
    def _parent(self, resource_id: str) -> Iterator[tuple[int, Path]]:
        root, path = self._target(resource_id)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root, flags)
        try:
            for component in path.relative_to(root).parts[:-1]:
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, path
        finally:
            os.close(fd)

    def _read_at(self, parent: int, path: Path, *, max_bytes: int | None = None) -> ResourceSnapshot:
        limit = min(self.max_file_bytes, max_bytes) if max_bytes is not None else self.max_file_bytes
        parent_stat = os.fstat(parent)
        metadata = {"parent_identity": [parent_stat.st_dev, parent_stat.st_ino]}
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return ResourceSnapshot(ResourceRevision(str(path), "absent"), None, None, metadata)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Only regular files are supported")
            if before.st_size > limit:
                raise ValueError("File exceeds the configured size limit")
            data = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
            if len(data) > limit or (before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ResourceConflictError("File changed while reading its preimage")
        mode = stat.S_IMODE(after.st_mode)
        identity = (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns, mode)
        version = hashlib.sha256(data + repr(identity).encode()).hexdigest()
        return ResourceSnapshot(ResourceRevision(str(path), version), data, mode, metadata)

    def read(self, resource_id: str, *, max_bytes: int | None = None) -> ResourceSnapshot:
        """Read a regular file or its absence, optionally lowering the configured byte cap."""
        if max_bytes is not None and (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0):
            raise ValueError("max_bytes must be a non-negative integer")
        with self._parent(resource_id) as (parent, path):
            return self._read_at(parent, path, max_bytes=max_bytes)

    def replace(self, expected: ResourceSnapshot, data: bytes | None, mode: int | None) -> ResourceSnapshot:
        """Check the preimage, fsync new bytes, atomically replace, then fsync the directory."""
        if data is not None and len(data) > self.max_file_bytes:
            raise ValueError("New content exceeds the configured size limit")
        with self._parent(expected.revision.resource_id) as (parent, path):
            if self._read_at(parent, path) != expected:
                raise ResourceConflictError("File or containing directory changed after preparation")
            if data is None:
                os.unlink(path.name, dir_fd=parent)
            else:
                temporary = f".protolink-{uuid.uuid4().hex}"
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fchmod(handle.fileno(), mode if mode is not None else 0o600)
                        os.fsync(handle.fileno())
                    if self._read_at(parent, path) != expected:
                        raise ResourceConflictError("File changed before atomic replacement")
                    if expected.data is None:
                        # link is atomic and refuses a target created since preparation.
                        os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    else:
                        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent)
                    except FileNotFoundError:
                        pass
            os.fsync(parent)
            return self._read_at(parent, path)


def filesystem_tools(
    *, roots: Sequence[str | Path], checkpoints: CheckpointStore | None = None, max_file_bytes: int = 8 * 1024 * 1024
) -> tuple[PreparedTool, ...]:
    """Create scoped read/list/search tools and optional recoverable write tools.

    Args:
        roots: Existing allowed directories; tool paths must be absolute. POSIX
            only. Symlinks below these roots are never followed.
        checkpoints: Supplying a CheckpointStore opts into create_file,
            replace_file, edit_file, preview_change, and restore_change. Omitting
            it exposes only read_file, list_files, and search_files.
        max_file_bytes: Per-file byte cap for reads, preimages, and new content.

    Reads and previews require ``filesystem.read``, writes ``filesystem.write``,
    and restoration ``filesystem.restore``. Use policies to require approval.
    Text uses UTF-8. edit_file requires a unique exact match unless replace_all is
    explicit; stale previews fail before mutation. Original bytes are preserved
    losslessly. Listing/search visit at most 10,000 entries and 20 directory levels;
    search reads at most 32 MiB in total. Results report incomplete scans. Existing
    callers supplying checkpoints retain their write/recovery tools.
    """
    from protolink.tools.builtins._filesystem_read import reading_tools

    resource = FilesystemResource(roots, max_file_bytes=max_file_bytes)
    reads = reading_tools(resource)
    if checkpoints is None:
        return reads
    checkpoint_store = checkpoints

    def create_file(path: str, content: str) -> dict[str, Any]:
        """Create a UTF-8 file, only when the approved target is still absent."""
        raise AssertionError("Signature only")

    def replace_file(path: str, content: str) -> dict[str, Any]:
        """Replace a file after approval of its exact preimage and proposed diff."""
        raise AssertionError("Signature only")

    def edit_file(path: str, old_text: str, new_text: str, *, replace_all: bool = False) -> dict[str, Any]:
        """Replace exact UTF-8 text with a recoverable diff; require a unique match unless replace_all=true."""
        raise AssertionError("Signature only")

    def preview_change(change_id: str) -> dict[str, Any]:
        """Inspect an earlier change, its restoration diff, and current conflicts."""
        raise AssertionError("Signature only")

    def restore_change(change_id: str) -> dict[str, Any]:
        """Restore earlier bytes/mode only if the current file matches that change."""
        raise AssertionError("Signature only")

    def load_change(change_id: str) -> ResourceChange:
        change = checkpoint_store.get(change_id)
        if change is None:
            raise ValueError("Unknown resource change")
        # Reapply allowed roots even to durable records supplied by storage.
        resource._target(change.before.revision.resource_id)
        return change

    def preview(before: ResourceSnapshot, data: bytes | None) -> Artifact:
        diff = "".join(
            difflib.unified_diff(
                (before.data or b"").decode("utf-8", "replace").splitlines(keepends=True),
                (data or b"").decode("utf-8", "replace").splitlines(keepends=True),
                fromfile=before.revision.resource_id,
                tofile=before.revision.resource_id,
            )
        )
        return Artifact(
            kind="preview",
            name="File change",
            uri=Path(before.revision.resource_id).as_uri(),
            parts=[Part.text(diff)],
            metadata={"preimage": before.revision.to_dict()},
        )

    def make_tool(signature: Any, capability: str) -> PreparedTool:
        name = signature.__name__

        def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
            del context
            args = dict(arguments)
            if name in {"create_file", "replace_file", "edit_file"}:
                before = resource.read(args["path"])
                if (before.data is None) != (name == "create_file"):
                    raise ResourceConflictError("Create requires absence; replace requires an existing file")
                if name == "edit_file":
                    old_text = args["old_text"]
                    if not old_text:
                        raise ValueError("old_text must not be empty")
                    text = (before.data or b"").decode("utf-8")
                    count = text.count(old_text)
                    if not count or (count != 1 and not args.get("replace_all", False)):
                        raise ValueError("old_text must match exactly once, or use replace_all for multiple matches")
                    data = text.replace(old_text, args["new_text"]).encode("utf-8")
                else:
                    data = args["content"].encode("utf-8")
                if len(data) > max_file_bytes:
                    raise ValueError("New content exceeds the configured size limit")
                args["path"] = before.revision.resource_id
                recovery: dict[str, Any] = {"before": before.to_dict(), "new_content": data.decode("utf-8")}
            else:
                change = load_change(args["change_id"])
                before = resource.read(change.before.revision.resource_id)
                data = change.before.data
                if name == "restore_change" and (change.state != "applied" or before != change.after):
                    raise ResourceConflictError("Restoration requires an applied change and matching postimage")
                recovery = {"before": before.to_dict(), "change": change.to_dict()}
            return RunAction(
                kind="tool.call",
                name=name,
                payload={"arguments": args, "recovery": recovery},
                capabilities=frozenset({capability}),
            ).with_artifacts([preview(before, data)])

        async def execute(execution: ToolExecution) -> dict[str, Any]:
            action = execution.authorization.action
            args = action.payload["arguments"]
            before = ResourceSnapshot.from_dict(action.payload["recovery"]["before"])
            execution.check()
            if name in {"preview_change", "restore_change"}:
                change = load_change(args["change_id"])
                if change.to_dict() != action.payload["recovery"]["change"]:
                    raise ResourceConflictError("Recovery record changed after approval")
                current = resource.read(before.revision.resource_id)
                if name == "preview_change":
                    return {
                        "change_id": change.change_id,
                        "state": change.state,
                        "uncertain": change.state in {"prepared", "restoring", "uncertain"},
                        "conflict": current != change.after,
                        "diff": preview(current, change.before.data).to_dict(),
                    }
                if current != before or current != change.after or change.state != "applied":
                    raise ResourceConflictError("Resource changed after restoration approval")
                data, mode = change.before.data, change.before.mode
                pending = replace(
                    change,
                    state="restoring",
                    restore_action_id=action.action_id,
                    restore_run_id=execution.context.run_id,
                    restore_task_id=execution.task_id,
                )
            else:
                data, mode = action.payload["recovery"]["new_content"].encode("utf-8"), before.mode
                pending = ResourceChange(
                    before=before,
                    after=None,
                    state="prepared",
                    action_id=action.action_id,
                    run_id=execution.context.run_id,
                    task_id=execution.task_id,
                )
            # These synchronous saves/I/O contain no cancellation await between
            # durable intent and mutation. Failure to save prevents the effect.
            checkpoint_store.save(pending)
            try:
                after = resource.replace(before, data, mode)
                completed = (
                    replace(pending, state="restored", restored_revision=after.revision)
                    if name == "restore_change"
                    else replace(pending, state="applied", after=after)
                )
                checkpoint_store.save(completed)
            except BaseException as exc:
                failed = replace(
                    pending, state="failed" if isinstance(exc, ResourceConflictError) else "uncertain", error=str(exc)
                )
                try:
                    checkpoint_store.save(failed)
                except Exception:
                    pass  # Existing durable prepared/restoring record remains an uncertainty marker.
                raise
            result = {
                "change_id": completed.change_id,
                "state": completed.state,
                "resource": after.revision.to_dict(),
                "action_id": action.action_id,
            }
            await execution.emit("resource.changed", **result)
            return result

        return PreparedTool(signature, prepare=prepare, execute=execute, capabilities=(capability,))

    return reads + tuple(
        make_tool(signature, capability)
        for signature, capability in (
            (create_file, "filesystem.write"),
            (replace_file, "filesystem.write"),
            (edit_file, "filesystem.write"),
            (preview_change, "filesystem.read"),
            (restore_change, "filesystem.restore"),
        )
    )
