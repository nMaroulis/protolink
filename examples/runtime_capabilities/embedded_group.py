"""Own agent lifecycle, consume events, cancel work, and obtain its report."""

import asyncio
import sys
import tempfile

from protolink import Agent, AgentCard, AgentGroup, CapabilityPolicy, Task
from protolink.tools.builtins import process_tool


async def main():
    agent = Agent(
        AgentCard(name="worker", description="Local worker", url="runtime://worker"),
        policy=CapabilityPolicy({"process.execute": "allow"}),
        verbosity=0,
    )
    agent.add_tool(process_tool())
    with tempfile.TemporaryDirectory() as directory:
        async with AgentGroup([agent]) as group:
            handle = group.run(
                "worker",
                Task.create_tool_call(
                    tool_name="execute_command",
                    args={
                        "argv": [sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(30)"],
                        "cwd": directory,
                        "env": {},
                    },
                ),
            )
            async for event in handle.events():
                if event.type == "process.output":
                    print(event.payload["text"].strip())
                    await handle.cancel("Application has seen enough output")
            result = await handle.result()
            print(result.status, len(result.report.events))
    # Direct local calls need no server. Configure transport="runtime" or an
    # existing network transport on each agent when discovery/remote calls are needed.


if __name__ == "__main__":
    asyncio.run(main())
