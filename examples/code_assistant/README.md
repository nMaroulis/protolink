# 🤖 Code Assistant — Multi-Agent Coding System

A simplified **"Claude Code"** built as a mesh of three autonomous agents using Protolink. This demo showcases how to build an AI coding assistant where specialized agents collaborate over the network — each with its own role, just like a real engineering team.

![Protolink](https://img.shields.io/badge/Protolink-Multi--Agent-blue)
![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)
![License MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## 🌟 Why This Example?

Coding assistants like Claude Code, Cursor, and GitHub Copilot are the most relatable AI applications for developers. Under the hood, they all share a similar architecture:

- A **brain** that reasons about code
- **hands** that read/write the filesystem
- A **coordinator** that manages the workflow

This example rebuilds that architecture using **Protolink's agent mesh**, demonstrating that you can build sophisticated AI systems by composing simple, autonomous agents.

---

## 🏗️ Architecture: Brain, Hands, and Coordinator

```
User Request: "Add docstrings to all functions in utils.py"
     │
     ▼
┌───────────────────────────────────────────────────────────┐
│                  ORCHESTRATOR AGENT                       │
│                  (LLM — Coordinator)                      │
│                                                           │
│  1. Receives user's coding request                        │
│  2. agent_call → coder.list_directory(".")                │
│  3. agent_call → coder.read_file("utils.py")              │
│  4. agent_call → planner.infer("Analyze & add docstrings")│
│  5. agent_call → coder.write_file("utils.py", new_code)   │
│  6. Summarizes changes to user                            │
└───────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────────┐      ┌─────────────────────────┐
│   PLANNER AGENT     │      │     CODER AGENT         │
│   (LLM — Brain)     │      │     (Tools — Hands)     │
│                     │      │                         │
│   • Analyzes tasks  │      │  • read_file()          │
│   • Creates plans   │      │  • write_file()         │
│   • Reviews code    │      │  • list_directory()     │
│   • Generates edits │      │  • search_in_files()    │
└─────────────────────┘      └─────────────────────────┘
         │                              │
         └──────────────┬───────────────┘
                        ▼
              ┌─────────────────┐
              │    REGISTRY     │
              │  (Discovery)    │
              └─────────────────┘
```

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/code_example_agents.png" alt="Code Assistant Agent Architecture" width="100%">
</div>

### The Agents

| Agent | Type | Protolink Feature | Purpose |
|-------|------|-------------------|---------|
| **Orchestrator** | LLM + Agent Calls | `agent_call` (both `infer` & `tool_call`) | User-facing coordinator. Receives coding requests and delegates to specialists. |
| **Planner** | LLM-only | `infer` (LLM-to-LLM delegation) | Pure reasoning. Analyzes code, creates plans, generates precise edits. No filesystem access. |
| **Coder** | Tools-only | `tool_call` (deterministic tools) | File operations. Reads, writes, lists, and searches files. No reasoning needed. |
| **Registry** | Discovery | Agent registration & lookup | Where agents register so they can discover each other dynamically. |

### Why Three Agents?

This mirrors how real coding assistants work:

- **Separation of Concerns**: The "brain" (Planner) doesn't touch files. The "hands" (Coder) don't reason. The Orchestrator coordinates.
- **Both Delegation Modes**: Planner gets `infer` calls (LLM-to-LLM), Coder gets `tool_call` calls — showcasing both A2A delegation modes.
- **Scalability**: In production, you could run the Planner on a powerful GPU, the Coder on a secure file server, and the Orchestrator as a lightweight API gateway.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) installed (free, local LLM) **OR** an API key for OpenAI / Anthropic

### 1. Install Protolink

```bash
pip install protolink
```

### 2. Set Up LLM

**Option A: Using Ollama (Free, Local)**
```bash
# Install Ollama from https://ollama.ai
ollama pull gemma4:latest
ollama serve
```

**Option B: Using OpenAI**
```bash
export OPENAI_API_KEY=sk-...
```

**Option C: Using Anthropic**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Run the Demo

```bash
cd examples/code_assistant

# Using Ollama (default)
LLM_PROVIDER=ollama python run.py

# Using OpenAI
LLM_PROVIDER=openai python run.py

# Using Anthropic
LLM_PROVIDER=anthropic python run.py

# With a specific query
python run.py "Add type hints to all functions in utils.py"
```

---

## 📋 Expected Output

```
🤖 CODE ASSISTANT — Protolink Multi-Agent Coding System
======================================================================

Architecture: Orchestrator (LLM) → Planner (LLM) + Coder (Tools)

📂 Setting up demo workspace...
   Created main.py
   Created utils.py
   Created config.py

📡 Starting Registry...
   Registry running at http://localhost:9000

🔧 Starting Coder Agent (tools-only, no LLM)...
   Coder running at http://localhost:8030
   Tools: ['read_file', 'write_file', 'list_directory', 'search_in_files']

🧠 Starting Planner Agent (LLM: openai)...
   Planner running at http://localhost:8020

🎯 Starting Orchestrator Agent (LLM: openai)...
   Orchestrator running at http://localhost:8010

🔍 Verifying agent discovery...
   Discovered 3 agents:
   • orchestrator (LLM): reasoning
   • planner (LLM): reasoning
   • coder (Tools): ['read_file', 'write_file', 'list_directory', 'search_in_files']

======================================================================
💬 Welcome to Code Assistant!
   Workspace: examples/code_assistant/workspace
   Files: main.py, utils.py, config.py

   Default: "Add docstrings to all functions in utils.py"

   >

📝 Processing: "Add docstrings to all functions in utils.py"
======================================================================

⏳ Orchestrator is working...

   📁 [coder] list_directory: .
   📁 [coder] → Found 3 entries in .

   📖 [coder] read_file: utils.py
   📖 [coder] → Read 27 lines from utils.py

   🧠 [planner] infer called: Here is the content of utils.py. Add clear docstrings...
   🧠 [planner] → def add(a, b):\n    """Add two numbers and return the result...

   ✍️  [coder] write_file: utils.py
   ✍️  [coder] → Wrote 52 lines to utils.py

======================================================================
✅ RESULT:
----------------------------------------------------------------------
I've added comprehensive docstrings to all 6 functions in `utils.py`:

📝 **Changes made:**
- `add(a, b)` — Added docstring explaining addition operation
- `subtract(a, b)` — Added docstring explaining subtraction
- `multiply(a, b)` — Added docstring explaining multiplication
- `divide(a, b)` — Added docstring with ValueError note for zero division
- `power(base, exponent)` — Added docstring explaining exponentiation
- `factorial(n)` — Added docstring with ValueError note for negatives

All docstrings follow PEP 257 conventions with parameter descriptions
and return value documentation.
----------------------------------------------------------------------
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM provider: `ollama`, `openai`, `anthropic`, `gemini` |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `gemma4:latest` | Ollama model to use |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `GEMINI_API_KEY` | - | Google Gemini API key |
| `WORKSPACE_DIR` | `./workspace` | Directory the Coder agent operates in |

---

## 📁 Project Structure

```
examples/code_assistant/
├── run.py                  # ⭐ Entry point — starts all agents & demo
├── orchestrator_agent.py   # LLM coordinator (delegates to Planner & Coder)
├── planner_agent.py        # LLM-only reasoning (code analysis & generation)
├── coder_agent.py          # Tools-only (read, write, list, search files)
├── .env.example            # Environment template
├── README.md               # This file
└── workspace/              # Demo Python project (auto-created)
    ├── main.py
    ├── utils.py
    └── config.py
```

---

## 🧠 How It Works — Step by Step


<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/code_example_steps.png" alt="Code Assistant Agent Steps" width="100%">
</div>


### 1. Agent Registration & Discovery

When the demo starts, each agent registers itself with the **Registry**:

```python
# Each agent registers automatically on start()
registry = Registry(url="http://localhost:9000", transport="http")
await registry.start()

agent = Agent(card={...}, transport="http", registry=registry)
await agent.start()  # ← Registers with the Registry
```

The Orchestrator then discovers all available agents:

```python
discovered = await orchestrator.discover_agents()
# Returns: [orchestrator_card, planner_card, coder_card]
```

### 2. Task Creation & Delegation

The user's request becomes a **Task** with an `infer` Part:

```python
task = Task.create_infer(prompt="Add docstrings to utils.py")
result = await client.send_task(agent_url=orchestrator_url, task=task)
```

### 3. The Inference Loop

The Orchestrator's LLM enters an **inference loop**:

1. **LLM thinks**: "I need to read the file first"
2. **LLM outputs**: `agent_call → coder.read_file(path="utils.py")`
3. **Protolink routes**: HTTP request to Coder → executes tool → returns result
4. **LLM observes**: File contents
5. **LLM thinks**: "Now I'll ask the Planner to generate docstrings"
6. **LLM outputs**: `agent_call → planner.infer(prompt="Add docstrings to: ...")`
7. **Protolink routes**: HTTP request to Planner → LLM generates code → returns
8. **LLM observes**: New code with docstrings
9. **LLM outputs**: `agent_call → coder.write_file(path="utils.py", content="...")`
10. **LLM outputs**: Final summary → loop ends

All of this happens **autonomously** — Protolink handles the routing, serialization, and response parsing.

---

## 🎯 Protolink Features Showcased

| # | Feature | Where |
|---|---------|-------|
| 1 | **`agent_call` with `infer`** | Orchestrator → Planner (LLM-to-LLM reasoning) |
| 2 | **`agent_call` with `tool_call`** | Orchestrator → Coder (file operations) |
| 3 | **Registry Discovery** | Agents find each other dynamically at runtime |
| 4 | **LLM-Agnostic** | One-line switch between OpenAI, Anthropic, Ollama |
| 5 | **Transport-Agnostic** | HTTP today, WebSocket/gRPC tomorrow |
| 6 | **Tool-Only Agents** | Coder has tools but no LLM — pure determinism |
| 7 | **LLM-Only Agents** | Planner has LLM but no tools — pure reasoning |
| 8 | **Custom handle_task** | Planner subclasses Agent for logging |
| 9 | **Autonomous Orchestration** | Multi-step workflow runs without human intervention |

---

## 💡 Try These Queries

```bash
python run.py "Add type hints to all functions in utils.py"
python run.py "Create a new test file for utils.py"
python run.py "Add error handling to the divide function"
python run.py "Refactor utils.py to use a Calculator class"
python run.py "Find all functions that don't have docstrings"
```

---

## 📄 License

MIT License — See [LICENSE](../../LICENSE) for details.

---

**Built with 💙 using [Protolink](https://github.com/nMaroulis/protolink)**
