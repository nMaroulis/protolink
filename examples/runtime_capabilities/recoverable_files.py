"""Approve an edit and a separate restoration; reject intervening changes."""

import asyncio
import tempfile
from pathlib import Path

from protolink import Agent, AgentCard, CapabilityPolicy, ResourceConflictError, StorageCheckpointStore
from protolink.storage import SQLiteStorage
from protolink.tools.builtins import filesystem_tools


async def approve(request, context):
    print(request.action.name, request.action.artifacts[0].parts[0].content)
    return True  # A real application obtains an explicit decision from its user.


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        checkpoints = StorageCheckpointStore(SQLiteStorage(str(root / "recovery.db"), namespace="file-changes"))
        agent = Agent(
            AgentCard(name="files", description="Recoverable files", url="runtime://files"),
            policy=CapabilityPolicy({"filesystem.write": "require_approval", "filesystem.restore": "require_approval"}),
            approval_handler=approve,
            verbosity=0,
        )
        for tool in filesystem_tools(roots=[root], checkpoints=checkpoints):
            agent.add_tool(tool)
        path = root / "note.txt"
        path.write_bytes(b"original\n")
        change = await agent.call_tool("replace_file", path=str(path), content="edited\n")
        await agent.call_tool("restore_change", change_id=change["change_id"])
        assert path.read_bytes() == b"original\n"
        change = await agent.call_tool("replace_file", path=str(path), content="another edit\n")
        path.write_text("external change\n")
        try:
            await agent.call_tool("restore_change", change_id=change["change_id"])
        except ResourceConflictError:
            print("Restoration declined: current content differs from the saved postimage")


if __name__ == "__main__":
    asyncio.run(main())
