# Protolink A2A Examples

This directory contains example implementations of agents and a client that demonstrate how to use the Protolink A2A library.

## Examples Overview

1. **Echo Agent** (`echo_agent.py`): A simple agent that echoes back messages and processes echo tasks.
2. **Task Processor Agent** (`task_processor_agent.py`): A more advanced agent that can handle various types of tasks including data processing, aggregation, and batch processing.
3. **Client Example** (`client_example.py`): A client script that demonstrates how to interact with the example agents.

## Prerequisites

- Python 3.8+
- Dependencies listed in `pyproject.toml`
- A running registry service (see the main README for setup instructions)

## Installation

1. Install the protolink package in development mode:
   ```bash
   pip install -e .
   ```

2. Install additional development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Running the Examples

### 1. Start the Registry Service

First, make sure you have a registry service running. You can use the example registry provided in the main repository.

### 2. Start the Echo Agent

In a new terminal window, run:

```bash
# Set environment variables
export AGENT_ID=echo-agent-1
export AGENT_NAME="Echo Agent"
export REGISTRY_URL=http://localhost:8000

# Run the echo agent
python examples/echo_agent.py
```

### 3. Start the Task Processor Agent

In another terminal window, run:

```bash
# Set environment variables
export AGENT_ID=task-processor-1
export AGENT_NAME="Task Processor"
export REGISTRY_URL=http://localhost:8000

# Run the task processor agent
python examples/task_processor_agent.py
```

### 4. Run the Client Example

In a third terminal window, run the client example to interact with the agents:

```bash
# Set environment variables
export REGISTRY_URL=http://localhost:8000

# Run the client example
python examples/client_example.py
```

The client will:
1. List all available agents
2. Send a message to the echo agent
3. Create and monitor a data processing task
4. Create and monitor a batch processing task

## Example Output

When you run the client, you should see output similar to the following:

```
=== Listing available agents ===
Found 2 agents:
- Echo Agent (ID: echo-agent-1, Capabilities: echo, ping)
- Task Processor (ID: task-processor-1, Capabilities: process_data, aggregate_results, batch_process)

=== Sending a message to the echo agent ===
Found echo agent: Echo Agent (ID: echo-agent-1)
Received response: {'message_id': '...', 'message_type': 'echo_response', ...}

=== Creating a data processing task ===
Found processor agent: Task Processor (ID: task-processor-1)
Created task: task-abc123
Waiting for task to complete...
Task status: running (progress: 20%)
Task status: running (progress: 40%)
Task status: completed (progress: 100%)
Task completed! Result: {'processed_data': ['APPLE', 'BANANA', ...]}

=== Creating a batch processing task ===
Found batch processor agent: Task Processor (ID: task-processor-1)
Created batch task: task-def456
Processing 15 items in batches of 5...
Waiting for batch task to complete...
Batch task status: running (progress: 33%)
Batch task status: running (progress: 66%)
Batch task status: completed (progress: 100%)
Batch task completed!
Processed 15 items in 3 batches
Sample results: [{'item': 'item-1', 'processed': True, 'result': 'Processed: item-1'}, ...]
```

## Customizing the Examples

You can customize the behavior of the agents and client by modifying the environment variables or the code directly. For example:

- Change the agent IDs, names, or capabilities
- Modify the task parameters or processing logic
- Add new message types or task handlers
- Implement additional security features

## Troubleshooting

- If you see connection errors, make sure the registry service is running and accessible at the specified URL.
- Check the logs of each agent for any error messages.
- Make sure all required environment variables are set correctly.
- If you encounter dependency issues, try reinstalling the package in development mode.

## Next Steps

- Explore the source code to understand how the agents and client are implemented.
- Try creating your own agent with custom message and task handlers.
- Extend the examples with additional features like authentication and encryption.
- Integrate the agents with your own applications and services.
