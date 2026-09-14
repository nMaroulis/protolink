"""Recovery inventory filters records without reading resources or changing states."""

from dataclasses import replace

import pytest

from protolink import ResourceRevision, StorageCheckpointStore
from protolink.core.resources import ResourceChange, ResourceSnapshot
from protolink.storage import InMemoryStorage, SQLiteStorage


@pytest.fixture(params=["memory", "sqlite"])
def checkpoints(request, tmp_path):
    storage = InMemoryStorage() if request.param == "memory" else SQLiteStorage(str(tmp_path / "checkpoints.db"))
    return StorageCheckpointStore(storage)


def change(index, **kwargs):
    return ResourceChange(
        before=ResourceSnapshot(
            ResourceRevision("/not/read/file", f"v{index}"), b"original\x00\xff", 0o640, {"nested": {"identity": index}}
        ),
        after=None,
        state="prepared",
        action_id=f"action-{index}",
        run_id="run",
        task_id="task",
        change_id=f"change-{index}",
        **kwargs,
    )


def test_inventory_filters_paginates_and_preserves_recovery_state(checkpoints):
    assert checkpoints.list_changes() == []
    first = change(1)
    second = replace(change(2), state="uncertain")
    third = replace(change(3), state="applied", run_id="other", task_id="other-task")
    for record in (first, second, third):
        checkpoints.save(record)
    assert checkpoints.list_changes() == [third, second, first]
    assert checkpoints.list_changes(limit=1, offset=1) == [second]
    assert checkpoints.list_changes(state="uncertain", resource_id="/not/read/file", run_id="run", task_id="task") == [
        second
    ]
    assert checkpoints.list_changes(run_id="run", limit=1, offset=1) == [first]
    assert checkpoints.list_changes(state="uncertain", run_id="other") == []
    assert checkpoints.list_changes(resource_id="/missing") == []
    assert checkpoints.list_changes(limit=0) == []
    assert checkpoints.list_changes(offset=10) == []
    for kwargs in ({"limit": -1}, {"offset": -1}):
        with pytest.raises(ValueError, match="non-negative"):
            checkpoints.list_changes(**kwargs)
    restored = replace(first, state="restored", restore_run_id="restore-run")
    checkpoints.save(restored)
    assert checkpoints.list_changes() == [third, second, restored]
    assert checkpoints.list_changes(run_id="restore-run") == []
    assert checkpoints.get(second.change_id).state == "uncertain"


def test_inventory_and_get_return_detached_lossless_records(checkpoints):
    original = change(1)
    checkpoints.save(original)
    for record in (checkpoints.list_changes()[0], checkpoints.get(original.change_id)):
        assert record.before.data == b"original\x00\xff"
        assert record.before.mode == 0o640
        record.before.metadata["nested"]["identity"] = "modified copy"
    assert checkpoints.get(original.change_id).before.metadata["nested"]["identity"] == 1
