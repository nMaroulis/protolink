"""Recovery records and filesystem conflicts use only temporary roots."""

import os
import stat

import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    CapabilityPolicy,
    ResourceConflictError,
    RunHandle,
    StorageCheckpointStore,
    Task,
)
from protolink.storage import SQLiteStorage
from protolink.tools.builtins import filesystem_tools
from protolink.tools.builtins.filesystem import FilesystemResource

pytestmark = pytest.mark.skipif(os.name != "posix", reason="FilesystemResource requires POSIX")


def configured(tmp_path, **kwargs):
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    store = StorageCheckpointStore(SQLiteStorage(str(tmp_path / "recovery.db")))
    agent = Agent(AgentCard(name="files", description="test", url="runtime://files"), verbosity=0, **kwargs)
    for tool in filesystem_tools(roots=[root], checkpoints=store):
        agent.add_tool(tool)
    return agent, root, store


@pytest.mark.asyncio
async def test_denied_create_and_denied_restore(tmp_path):
    a, root, _ = configured(tmp_path, policy=CapabilityPolicy({"filesystem.write": "deny"}))
    with pytest.raises(ActionDeniedError):
        await a.call_tool("create_file", path=str(root / "x"), content="hi")
    assert not (root / "x").exists()
    a.action_authorizer.policy = CapabilityPolicy({"filesystem.restore": "deny"})
    result = await a.call_tool("create_file", path=str(root / "x"), content="hi")
    with pytest.raises(ActionDeniedError):
        await a.call_tool("restore_change", change_id=result["change_id"])
    assert (root / "x").read_text() == "hi"


@pytest.mark.asyncio
async def test_original_bytes_mode_persistence_and_restore_conflict(tmp_path):
    a, root, store = configured(tmp_path)
    path = root / "x"
    path.write_bytes(b"original\x00\xff")
    path.chmod(0o640)
    task = Task.create_tool_call(tool_name="replace_file", args={"path": str(path), "content": "new"})
    result = await RunHandle.start(a, task).result()
    receipt = next(event.payload["result"] for event in result.report.events if event.type == "action.completed")
    change_id = receipt["change_id"]
    persisted = StorageCheckpointStore(SQLiteStorage(str(tmp_path / "recovery.db"))).get(change_id)
    assert persisted.before.data == b"original\x00\xff"
    assert persisted.before.mode == 0o640
    assert persisted.task_id == task.id and persisted.run_id and persisted.action_id
    assert persisted.state == "applied"
    restored = await a.call_tool("restore_change", change_id=change_id)
    assert restored["state"] == "restored"
    assert path.read_bytes() == b"original\x00\xff"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert store.get(change_id).restore_action_id != persisted.action_id
    with pytest.raises(ResourceConflictError):
        await a.call_tool("restore_change", change_id=change_id)
    receipt = await a.call_tool("replace_file", path=str(path), content="second")
    path.write_text("external change")
    preview = await a.call_tool("preview_change", change_id=receipt["change_id"])
    assert preview["conflict"]
    with pytest.raises(ResourceConflictError):
        await a.call_tool("restore_change", change_id=receipt["change_id"])
    assert path.read_text() == "external change"


@pytest.mark.asyncio
async def test_stale_preview_rejected_after_approval(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    path = root / "x"
    path.write_text("before")

    async def approve(request, context):
        assert "before" in request.action.artifacts[0].parts[0].content
        path.write_text("changed while deciding")
        return True

    a, _, store = configured(
        tmp_path, policy=CapabilityPolicy({"filesystem.write": "require_approval"}), approval_handler=approve
    )
    with pytest.raises(ResourceConflictError):
        await a.call_tool("replace_file", path=str(path), content="proposed")
    assert path.read_text() == "changed while deciding"
    assert next(iter(store.storage.load().values()))["state"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "outside", "traversal"])
async def test_path_and_symlink_boundaries(tmp_path, kind):
    a, root, _ = configured(tmp_path)
    real = root / "real"
    real.mkdir()
    (real / "x").write_text("untouched")
    if kind == "file":
        (root / "link").symlink_to(real / "x")
        path = root / "link"
    elif kind == "directory":
        (root / "link").symlink_to(real, target_is_directory=True)
        path = root / "link" / "x"
    elif kind == "dangling":
        (root / "link").symlink_to(real / "missing")
        path = root / "link"
    elif kind == "outside":
        path = tmp_path / "outside"
    else:
        path = root / ".." / "outside"
    with pytest.raises((ValueError, OSError)):
        await a.call_tool("replace_file", path=str(path), content="bad")
    assert (real / "x").read_text() == "untouched"


@pytest.mark.asyncio
async def test_directory_swap_after_approval_cannot_redirect_write(tmp_path):
    a, root, _ = configured(tmp_path)
    directory = root / "directory"
    directory.mkdir()
    path = directory / "x"
    path.write_text("original")

    async def approve(request, context):
        directory.rename(root / "old-directory")
        directory.mkdir()
        path.write_text("replacement directory")
        return True

    a.action_authorizer.policy = CapabilityPolicy(default_effect="require_approval")
    a.action_authorizer.approval_handler = approve
    with pytest.raises(ResourceConflictError):
        await a.call_tool("replace_file", path=str(path), content="bad")
    assert path.read_text() == "replacement directory"
    assert (root / "old-directory" / "x").read_text() == "original"


@pytest.mark.asyncio
async def test_persistence_failure_prevents_effect_and_interrupted_receipt_is_uncertain(tmp_path, monkeypatch):
    a, root, store = configured(tmp_path)
    save = store.save

    def fail_save(change):
        raise OSError("storage unavailable")

    monkeypatch.setattr(store, "save", fail_save)
    with pytest.raises(OSError):
        await a.call_tool("create_file", path=str(root / "x"), content="hi")
    assert not (root / "x").exists()

    def fail_receipt(change):
        if change.state != "prepared":
            raise OSError("interrupted after mutation")
        save(change)

    monkeypatch.setattr(store, "save", fail_receipt)
    with pytest.raises(OSError):
        await a.call_tool("create_file", path=str(root / "x"), content="hi")
    assert (root / "x").read_text() == "hi"
    change_id = next(iter(store.storage.load()))
    preview = await a.call_tool("preview_change", change_id=change_id)
    assert preview["uncertain"]
    with pytest.raises(ResourceConflictError):
        await a.call_tool("restore_change", change_id=change_id)


@pytest.mark.asyncio
async def test_interrupted_atomic_replace_preserves_original(tmp_path, monkeypatch):
    a, root, store = configured(tmp_path)
    path = root / "x"
    path.write_bytes(b"old")

    def fail_replace(*args, **kwargs):
        raise OSError("simulated interruption")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        await a.call_tool("replace_file", path=str(path), content="new")
    assert path.read_bytes() == b"old"
    assert not list(root.glob(".protolink-*"))
    assert next(iter(store.storage.load().values()))["state"] == "uncertain"


def test_resource_revision_changes_for_same_bytes_rewrite(tmp_path):
    path = tmp_path / "x"
    path.write_bytes(b"same")
    resource = FilesystemResource([tmp_path])
    revision = resource.read(str(path)).revision
    path.write_bytes(b"same")
    assert resource.read(str(path)).revision != revision
