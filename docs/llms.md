# LLMs

Protolink integrates with various LLM backends.

## LLM Types

Protolink groups LLM backends into three broad categories:

- **API** — calls a remote API and requires an API key:
  - `OpenAILLM`: uses the **OpenAI API** for sync & async requests.
  - `AnthropicLLM`: uses the **Anthropic API** for sync & async requests.

- **Local** — runs the model directly in your runtime:
  - `LlamaCPPLLM`: uses a local **llama.cpp** runtime for sync & async requests.

- **Server** — connects to an LLM server, locally or remotely:
  - `OllamaLLM`: connects to an **Ollama** server for sync & async requests.

You can also use other LLM clients directly without going through Protolink’s `LLM` wrappers if you prefer.

## Configuration

Configuration depends on the specific backend, but the general pattern is:

1. **Install the relevant extras** (from the README):

   ```bash
   # All supported LLM backends
   uv add "protolink[llms]"
   ```

   !!! info "Choosing LLM extras"
       If you only need a subset of backends, you can install more targeted extras once they are exposed (for example, only OpenAI or only local backends).

2. **Instantiate the LLM** with the desired model and credentials:

   ```python
   from protolink.llms.api import OpenAILLM


   llm = OpenAILLM(
       model="gpt-5.1",
       # api_key is typically read from the environment, e.g. OPENAI_API_KEY
   )
   ```

   !!! warning "API keys"
       Never commit API keys to version control. Read them from environment variables or a secure secrets manager.

3. **Pass the LLM to your Agent**:

   ```python
   from protolink.agents import Agent
   from protolink.models import AgentCard
   from protolink.transport import HTTPTransport


   agent_card = AgentCard(name="llm_agent", description="Agent backed by an LLM")
   transport = HTTPTransport()

   agent = Agent(agent_card, transport, llm)
   ```

For local and server‑style LLMs (`LlamaCPPLLM`, `OllamaLLM`), configuration additionally includes paths to model files or server URLs. Refer to the corresponding example scripts in `examples/llms.py` for concrete usage patterns.

