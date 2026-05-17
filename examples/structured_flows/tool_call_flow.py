import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from protolink.agents import Agent
from protolink.flows import Pipeline
from protolink.models import Message, Part, Task


def main():
    print("=" * 70)
    print("🚀 Structured Flow: Cross-Agent Tool Execution Example")
    print("=" * 70)

    # 1. Define an Agent with a Tool
    calc_agent = Agent(
        card={"name": "calculator", "url": "http://localhost:8041", "description": "Provides math tools"},
        transport="http",
    )

    # Add a simple tool
    @calc_agent.tool(name="add", description="Adds two numbers")
    async def add(a: int, b: int) -> int:
        print(f"   [ToolProvider] Executing 'add' tool with {a} and {b}")
        return a + b

    # 2. Define an Agent that "Calls" the tool by constructing a task
    class RequesterAgent(Agent):
        def __init__(self):
            super().__init__(
                card={"name": "requester", "url": "http://localhost:8042", "description": "Requests tool execution"},
                transport="http",
            )

        async def handle_task(self, task: Task) -> Task:
            print(f"   [{self.card.name}] Constructing a tool_call Part for the next step...")

            # This agent doesn't execute anything, it just appends a tool_call instruction
            # for whoever receives the task next.
            msg = Message(
                role="agent", parts=[Part.tool_call(tool_name="add", args={"a": 10, "b": 32}, call_id="call_123")]
            )
            task.add_message(msg)
            return task

    req_agent = RequesterAgent()

    # 3. Build a Pipeline
    # Step 1: Requester constructs the call
    # Step 2: Calculator executes the call
    print("\n📦 Building pipeline...")
    flow = Pipeline().add_step(req_agent).add_step(calc_agent)

    print("✅ Flow: Requester -> ToolProvider")

    # 4. Execute
    print("\n🟢 Executing flow...")
    task = Task.create(Message.user("Please add 10 and 32."))

    # Sync execution
    # For async use await flow.execute(task)
    result = flow.sync.execute(task)

    print("\n" + "-" * 40)
    print("🏁 Execution Results")
    print("-" * 40)

    # The last part should be the tool_output
    last_item = result.get_last_item()
    if last_item:
        for part in last_item.parts:
            if part.type == "tool_output":
                res = part.content.result if hasattr(part.content, "result") else part.content.get("result")
                print(f"✅ Success! Tool Output: {res}")
            elif part.type == "error":
                msg = part.content.message if hasattr(part.content, "message") else part.content.get("message")
                print(f"❌ Error: {msg}")

    print(f"\nTask History ({len(result.messages)} messages, {len(result.artifacts)} artifacts):")
    for i, msg in enumerate(result.messages):
        print(f"  Msg {i}: Role={msg.role}, Parts={[p.type for p in msg.parts]}")


if __name__ == "__main__":
    main()
