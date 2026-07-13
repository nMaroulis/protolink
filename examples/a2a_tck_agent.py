"""Provider-free agent used as the System Under Test for the A2A 1.0 TCK.

Run this fixture from the repository root:

    uv run python examples/a2a_tck_agent.py

The fixture is deterministic and deliberately has no LLM or external provider.
It is only a TCK target; running it does not by itself establish A2A
compatibility. The official TCK report is the evidence for that claim.
"""

from __future__ import annotations

import os

from protolink import Agent, AgentCard, Artifact, Message, Part, Task

DEFAULT_AGENT_URL = "http://127.0.0.1:9999"


class A2ATCKAgent(Agent):
    """Return stable responses for the official TCK's provider-free scenarios."""

    async def handle_task(self, task: Task) -> Task:
        """Handle one task without a model, network dependency, or randomness."""
        message = task.messages[-1] if task.messages else None
        message_id = message.id if message is not None else ""

        if message_id.startswith("tck-input-required"):
            return task.require_input(Message.agent("Additional input is required"))

        if message_id.startswith("tck-artifact-file-url"):
            task.complete("Hello from TCK")
            task.add_artifact(
                Artifact(
                    name="output.txt",
                    media_type="text/plain",
                    parts=[
                        Part(
                            type="file",
                            content={
                                "url": "https://example.com/output.txt",
                                "filename": "output.txt",
                                "media_type": "text/plain",
                            },
                        )
                    ],
                )
            )
            return task

        if message_id.startswith("tck-artifact-file"):
            task.complete("Hello from TCK")
            task.add_artifact(
                Artifact(
                    name="output.txt",
                    media_type="text/plain",
                    parts=[
                        Part(
                            type="file",
                            content={
                                "raw": "R2VuZXJhdGVkIGZpbGUgY29udGVudA==",
                                "filename": "output.txt",
                                "media_type": "text/plain",
                            },
                        )
                    ],
                )
            )
            return task

        if message_id.startswith("tck-artifact-data"):
            task.complete("Hello from TCK")
            task.add_artifact(Artifact(parts=[Part.json({"key": "value", "count": 42})]))
            return task

        if message_id.startswith("tck-artifact-text"):
            task.complete("Hello from TCK")
            task.add_artifact(Artifact(parts=[Part.text("Generated text content")]))
            return task

        if message_id.startswith("tck-message-response"):
            # The A2A binding may translate this completed single-message task
            # into the protocol's direct Message response variant.
            task.metadata["a2a_response_kind"] = "message"
            return task.complete("Direct message response")

        return task.complete("Hello from TCK")


def main() -> None:
    """Serve the deterministic TCK fixture on localhost until interrupted."""
    agent_url = os.environ.get("PROTOLINK_A2A_TCK_URL", DEFAULT_AGENT_URL)
    agent = A2ATCKAgent(
        AgentCard(
            name="protolink-a2a-tck",
            description="Provider-free deterministic agent for A2A 1.0 compatibility testing",
            url=agent_url,
            transport="http",
        ),
        transport="http",
        verbosity=0,
    )

    print(f"Starting the ProtoLink A2A TCK fixture at {agent_url}", flush=True)
    try:
        agent.start(register=False)
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
