# 🏖️ Vacation Booking System - Multi-Agent Demo

A **decentralized, autonomous vacation booking system** showcasing Protolink's multi-agent orchestration capabilities. This demo builds a mesh of specialized agents that collaborate to plan and book a trip to Greece.

![Protolink](https://img.shields.io/badge/Protolink-Multi--Agent-blue)
![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)
![License MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## 🌟 Why This Matters

The landscape of AI agents is shifting. We're moving away from monolithic scripts driven by a single giant model, towards **Multi-Agent Systems (MAS)** where specialized, autonomous agents collaborate to solve complex problems.

But today's frameworks often trap you in a walled garden:
- Locked into a specific LLM (OpenAI, Anthropic, etc.)
- Locked into a specific Transport for communication
- Locked into a specific runtime
- Locked into specific Tooling schemes

**Protolink breaks away from this model.** In Protolink, an Agent is an autonomous, centralized object that serves as the core unit of your system. It is designed to be fully modular, so you can plug in any LLM, Tools, Transport, Storage, OpenTelemetry and Authentication stack you need.

---

## 🏗️ Architecture: A Mesh of Specialists

We build a team of four agents. They don't just "call" each other as functions; they communicate over HTTP using Protolink's standard `agent_call` protocol.

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/ticket_example_architecture.png" alt="Agent Architecture" width="100%">
</div>

### The Agents

| Agent | Type | Purpose |
|-------|------|---------|
| **Coordinator** | LLM + Tools | User-facing orchestrator. Breaks down requests and delegates to specialists. |
| **Holiday Advisor** | LLM | Pure reasoning agent. Evaluates destinations and provides recommendations. |
| **Weather Agent** | Tools | Deterministic agent providing weather forecasts. |
| **Hotel Agent** | Tools | Deterministic agent executing bookings. |
| **Registry** | Discovery | Where agents register to discover each other. |

### Communication Flow

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/ticket_example_flowchart.png" alt="Agent Flowchart" width="100%">
</div>

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                    COORDINATOR AGENT                        │
│                    (Has LLM - GPT-4/Llama3)                │
│                                                             │
│  1. Receives: "Book me a vacation to Santorini"            │
│  2. Thinks: "I need to check weather first"                │
│  3. agent_call → weather_agent.get_weather()               │
│  4. Observes: "Weather is sunny, 32°C - perfect!"          │
│  5. Thinks: "Now I can book the hotel"                     │
│  6. agent_call → hotel_agent.book_hotel()                  │
│  7. Observes: "Booking confirmed: HTL-ABC123"              │
│  8. Returns: Complete vacation summary                     │
└─────────────────────────────────────────────────────────────┘
          │                           │
          ▼                           ▼
┌─────────────────────┐     ┌─────────────────────┐
│   WEATHER AGENT     │     │    HOTEL AGENT      │
│   (Tool-only)       │     │    (Tool-only)      │
│                     │     │                     │
│  get_weather()      │     │  book_hotel()       │
│  - Location         │     │  - Location         │
│  - Date             │     │  - Check-in/out     │
│                     │     │  - Guests, Budget   │
└─────────────────────┘     └─────────────────────┘
          │                           │
          └─────────────┬─────────────┘
                        ▼
              ┌─────────────────┐
              │    REGISTRY     │
              │  (Discovery)    │
              └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) installed (free, local LLM) **OR** OpenAI API key

### 1. Install Protolink

```bash
pip install protolink
```

### 2. Set Up LLM

**Option A: Using Ollama (Free, Local)**
```bash
# Install Ollama from https://ollama.ai
ollama pull llama3:8b
ollama serve
```

**Option B: Using OpenAI**
```bash
# Set your API key
export OPENAI_API_KEY=sk-...
```

### 3. Run the Demo

**All-in-One Script (Recommended)**

The fastest way to see everything in action—all agents defined in a single file:

```bash
cd examples/ticket_booking
python quickstart.py
```

**Or run modular scripts separately:**

```bash
# Using Ollama (default)
python run.py

# Using OpenAI
OPENAI_API_KEY=sk-... LLM_PROVIDER=openai python run.py
```

---

## 📋 Expected Output

```
✅ RESULT:
----------------------------------------------------------------------
Great news! I've successfully booked your relaxing vacation to Santorini!

🌤️ **Weather Report for Santorini (July 2026):**
- Temperature: 32°C (86°F)
- Conditions: Sunny
- Humidity: 50%
- Wind: Light breeze
- Verdict: Perfect weather for a beach vacation!

🏨 **Hotel Booking Confirmed:**
- Hotel: Aegean Sunset Suites ⭐⭐⭐⭐
- Location: Santorini
- Check-in: July 15, 2026 at 15:00
- Check-out: July 20, 2026 at 11:00
- Duration: 5 nights
- Room: Double Room for 2 guests
- Amenities: Pool, Spa, Breakfast, Sea View
- Total Price: €1400 EUR
- Booking ID: HTL-DAS98DA8D79D2JD9
- Cancellation: Free until 24h before check-in

Have a wonderful trip! 🏖️
----------------------------------------------------------------------
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM provider: `ollama` or `openai` |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3:8b` | Ollama model to use |
| `OPENAI_API_KEY` | - | OpenAI API key (if using OpenAI) |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |
| `GEMINI_API_KEY` | - | Google Gemini API key |

### Supported LLM Providers

```python
# API-based
from protolink.llms.api import OpenAILLM, AnthropicLLM, GeminiLLM, DeepSeekLLM, GrokLLM

# Server-based
from protolink.llms.server import OllamaLLM

# Use any provider
llm = OpenAILLM(model="gpt-4o")
llm = AnthropicLLM(model="claude-3.5-sonnet")
llm = OllamaLLM(model="llama3:8b")
```

---

## 📁 Project Structure

```
examples/ticket_booking/
├── quickstart.py           # ⭐ All-in-one script (recommended)
├── run.py                  # Modular entry point
├── coordinator_agent.py    # LLM-powered orchestrator
├── holiday_advisor.py      # LLM reasoning agent
├── weather_agent.py        # Weather forecast tool
├── hotel_booking_agent.py  # Hotel booking tool
├── .env.example            # Environment template
└── README.md               # This file
```

---

## 🧠 How It Works

### Task & Parts

A **Task** is the top-level container that includes Messages or Artifacts. Each Message contains **Parts**, the atomic units of action:

| Part Type | Description |
|-----------|-------------|
| `infer` | Request an agent's LLM to reason about a prompt |
| `infer_output` | The final response produced by the LLM |
| `tool_call` | Execute an agent's specific tool with arguments |
| `tool_output` | The result returned by a tool execution |

### Example Task

```python
from protolink.models import Task

user_query = "Book me a relaxing vacation to Santorini for 5 nights in mid-July 2026"
task = Task.create_infer(prompt=user_query)
```

This creates:

```json
{
  "id": "task_1f2a3b4c5d6e7f8g",
  "messages": [
    {
      "role": "user",
      "parts": [
        {
          "type": "infer",
          "prompt": "Book me a relaxing vacation to Santorini for 5 nights in mid-July 2026"
        }
      ]
    }
  ],
  "status": "pending"
}
```

### Sending Tasks with AgentClient

```python
from protolink.client import AgentClient

client = AgentClient(transport="http", url="http://localhost:8050")
result = await client.send_task(agent_url="http://localhost:8010", task=task)
print(result.get_last_part_content())
```

---

## 🎯 Key Takeaways

1. **Transport Independence**: Agents speak HTTP today, but can speak WebSockets, gRPC, or in-memory queues tomorrow without changing agent code.

2. **LLM Agnostic**: Switch between providers with one line change. Use OpenAI, Anthropic, Gemini, Ollama, or any other supported provider.

3. **Universal Tooling**: Supports the Model Context Protocol (MCP) via built-in adapters. Import tools from thousands of existing MCP servers instantly.

4. **Separation of Concerns**: Each agent has a single responsibility. Only agents that need reasoning get an LLM; specialists are pure tools.

5. **Dynamic Discovery**: Agents find each other through the Registry at runtime—no hard-coded references.

6. **Automatic Orchestration**: The inference loop handles multi-step workflows automatically.

---

## 📄 License

MIT License - See [LICENSE](../../LICENSE) for details.

---

**Built with 💙 using [Protolink](https://github.com/nMaroulis/protolink)**
