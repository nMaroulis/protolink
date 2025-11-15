"""
ProtoLink v0.2.0 Example: Streaming Task with Progress Updates

This example demonstrates the NEW v0.2.0 features:
- Real-time streaming task updates
- Context management for multi-turn conversations
- Artifact production and streaming
- Task progress events

Run with:
    python streaming_agent_example.py
"""

import asyncio

from protolink.agent import Agent
from protolink.core.events import TaskArtifactUpdateEvent, TaskProgressEvent, TaskStatusUpdateEvent
from protolink.models import AgentCard, Artifact, Message, Task
from protolink.transport import RuntimeTransport


class StreamingAnalysisAgent(Agent):
    """Agent that processes data with real-time progress updates."""

    def __init__(self):
        card = AgentCard(
            name="analysis-agent",
            description="Performs data analysis with streaming progress",
            url="local://analysis-agent",
            capabilities={"streaming": True},
        )
        super().__init__(card)

    def handle_task(self, task: Task) -> Task:
        """Synchronous task handler (for non-streaming clients)."""
        user_text = task.messages[0].parts[0].content

        # Create artifact with result
        result = Artifact().add_text(f"Analysis of: {user_text}")
        task.add_artifact(result)

        return task.complete("Analysis complete")

    async def handle_task_streaming(self, task: Task):
        """NEW in v0.2.0: Streaming task handler with progress events."""
        # Add to context (NEW in v0.2.0)
        context = self.context_manager.create_context()
        task.metadata["context_id"] = context.context_id

        # Emit start event
        yield TaskStatusUpdateEvent(task_id=task.id, previous_state="submitted", new_state="working")

        user_text = task.messages[0].parts[0].content
        print(f"[Agent] Starting analysis of: {user_text}")

        # Simulate work with progress updates
        for step in range(1, 5):
            await asyncio.sleep(0.5)  # Simulate work

            progress = step * 20
            yield TaskProgressEvent(task_id=task.id, progress=progress, message=f"Processing step {step}/4")
            print(f"[Agent] Progress: {progress}%")

        # Produce artifact (NEW in v0.2.0)
        await asyncio.sleep(0.5)
        artifact = Artifact().add_text(f"Analysis Results for: {user_text}\n\nData processed: 1000 records\nErrors: 0")
        artifact.metadata["type"] = "analysis_result"

        yield TaskArtifactUpdateEvent(task_id=task.id, artifact=artifact)
        print("[Agent] Artifact produced")

        # Emit completion event
        yield TaskStatusUpdateEvent(task_id=task.id, previous_state="working", new_state="completed", final=True)
        print("[Agent] Analysis complete")


async def main():
    print("=== ProtoLink v0.2.0: Streaming Task Example ===\n")

    # Create agent and transport
    agent = StreamingAnalysisAgent()
    transport = RuntimeTransport()
    transport.register_agent(agent)

    # Create task
    task = Task.create(Message.user("Analyze customer data"))

    print("Starting streaming task...\n")

    # Subscribe to task updates (NEW in v0.2.0)
    event_count = 0
    async for event_data in transport.subscribe_task("analysis-agent", task):
        event_count += 1
        event_type = event_data.get("type", "unknown")

        if event_type == "task_status_update":
            state = event_data["new_state"]
            final = event_data.get("final", False)
            print(f"[Event {event_count}] Status: {state} (final={final})")

        elif event_type == "task_progress":
            progress = event_data["progress"]
            message = event_data.get("message", "")
            print(f"[Event {event_count}] Progress: {progress}% - {message}")

        elif event_type == "task_artifact_update":
            artifact = event_data.get("artifact", {})
            artifact_id = artifact.get("artifact_id", "unknown")
            print(f"[Event {event_count}] Artifact: {artifact_id}")
            if artifact.get("parts"):
                part_content = artifact["parts"][0].get("content", "")
                print(f"    Content preview: {part_content[:60]}...")

    print(f"\n✅ Streaming complete! Received {event_count} events")

    # Show context info (NEW in v0.2.0)
    context_id = task.metadata.get("context_id")
    if context_id:
        context = agent.context_manager.get_context(context_id)
        if context:
            print("\n📝 Context Info:")
            print(f"   Context ID: {context_id}")
            print(f"   Messages in context: {len(context.messages)}")
            print(f"   Created: {context.created_at}")


async def example_multi_turn():
    """Example of multi-turn conversation using context (NEW in v0.2.0)."""
    print("\n=== ProtoLink v0.2.0: Multi-Turn Context Example ===\n")

    agent = StreamingAnalysisAgent()
    transport = RuntimeTransport()
    transport.register_agent(agent)

    # Create a context for multi-turn conversation
    context = agent.context_manager.create_context()
    print(f"Created context: {context.context_id}\n")

    # Turn 1
    print("Turn 1: User sends first message")
    msg1 = Message.user("What's the status?")
    agent.context_manager.add_message_to_context(context.context_id, msg1)
    print(f"  Messages in context: {agent.context_manager.get_context_message_count(context.context_id)}")

    # Turn 2
    await asyncio.sleep(0.5)
    print("\nTurn 2: Agent responds")
    msg2 = Message.agent("Status: Processing")
    agent.context_manager.add_message_to_context(context.context_id, msg2)
    print(f"  Messages in context: {agent.context_manager.get_context_message_count(context.context_id)}")

    # Turn 3
    await asyncio.sleep(0.5)
    print("\nTurn 3: User follows up")
    msg3 = Message.user("How much longer?")
    agent.context_manager.add_message_to_context(context.context_id, msg3)
    print(f"  Messages in context: {agent.context_manager.get_context_message_count(context.context_id)}")

    # Show full context
    context = agent.context_manager.get_context(context.context_id)
    print("\nFull context history:")
    for i, msg in enumerate(context.messages, 1):
        print(f"  {i}. {msg.role}: {msg.parts[0].content if msg.parts else '(no content)'}")


if __name__ == "__main__":
    # Run streaming example
    asyncio.run(main())

    # Run multi-turn example
    asyncio.run(example_multi_turn())
