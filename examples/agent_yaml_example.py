"""
Agent YAML Export and Import Example

This example demonstrates how to:
1. Initialize an Agent with a card, transport, and a native tool.
2. Export the agent configuration to a YAML file.
3. Import the agent configuration from the YAML file to reconstruct the Agent.
4. Verify the imported agent's state and capabilities.
"""

import os

from protolink.agents import Agent


# 1. Define a dummy/example tool function
async def calculate_square(number: int) -> int:
    """Calculates the square of a number."""
    return number * number


def run_example():
    # 2. Configure a basic agent
    agent_card = {
        "name": "math-agent",
        "description": "An agent that performs math operations",
        "url": "local://math-agent",
    }

    # Initialize the agent with 'runtime' transport
    original_agent = Agent(
        card=agent_card,
        transport="runtime",
        verbosity=2,
    )

    # Register our tool
    # Note: Because the tool wraps calculate_square, its function path is dynamically resolvable
    original_agent.tool(
        name="calculate_square",
        description="Calculates the square of a number",
    )(calculate_square)

    print("\n=== ORIGINAL AGENT ===")
    print(f"Name: {original_agent.card.name}")
    print(f"URL:  {original_agent.card.url}")
    print(f"Tools: {list(original_agent.tools.keys())}")
    print(f"Transport: {original_agent.transport.transport_type if original_agent.transport else None}")

    # 3. Export to YAML file
    yaml_path = "math_agent_config.yaml"
    print(f"\nExporting original agent to '{yaml_path}'...")
    original_agent.to_yaml(yaml_path)

    # Let's read the YAML string to inspect it
    with open(yaml_path, encoding="utf-8") as f:
        yaml_content = f.read()
    print("\n--- YAML File Content ---")
    print(yaml_content)
    print("-------------------------")

    # 4. Import from YAML file
    print(f"\nImporting agent from '{yaml_path}'...")
    imported_agent = Agent.from_yaml(yaml_path)

    print("\n=== IMPORTED AGENT ===")
    print(f"Name: {imported_agent.card.name}")
    print(f"URL:  {imported_agent.card.url}")
    print(f"Tools: {list(imported_agent.tools.keys())}")
    print(f"Transport: {imported_agent.transport.transport_type if imported_agent.transport else None}")

    # 5. Verify and call a tool on the imported agent
    print("\nVerifying imported agent tool invocation...")
    try:
        # We can call the tool synchronously using the sync API convenience wrapper
        result = imported_agent.sync.invoke(
            message="",
            part_type="tool_call",
            tool_name="calculate_square",
            tool_args={"number": 12},
        )
        print(f"Invocation Result (calculate_square of 12): {result}")
        assert "144" in str(result)
        print("Success! Imported agent successfully resolved and executed the tool.")
    except Exception as e:
        print(f"Failed to execute tool on imported agent: {e}")

    # Clean up the configuration file
    if os.path.exists(yaml_path):
        os.remove(yaml_path)
        print(f"\nCleaned up '{yaml_path}'.")


if __name__ == "__main__":
    run_example()
