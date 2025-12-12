# Examples

This section links to example projects and code snippets in the repository.

## HTTP Agents

The repository includes several examples under the `examples/` directory. For HTTP‑based agents:

- `examples/http_agents.py` — basic HTTP transport example showing how to spin up an HTTP‑enabled agent.
- `examples/http_math_agents.py` — example of delegating between agents over HTTP (e.g. a question agent calling a math agent).

## Other Examples

Additional examples illustrate other capabilities:

- `examples/basic_agent.py` — minimal agent setup focused on core concepts.
- `examples/llms.py` — examples of wiring different LLM backends into agents.
- `examples/runtime_agents.py` — demonstrates using `RuntimeTransport` for in‑process agent communication.
- `examples/streaming_agent.py` — shows streaming behaviour (e.g. via WebSocket or other streaming‑capable transports).
- `examples/oauth_agent.py` — demonstrates OAuth 2.0 and API‑key based security in front of agents.

You can run and adapt these scripts as starting points for your own agent systems.

!!! tip "New here?"
    Start with `examples/basic_agent.py` to understand the core concepts, then move on to `examples/http_agents.py` for HTTP-based setups.


<h3 style="text-align: center;"> 🎉🎉 Congratulations, You made it! 🎉🎉 </h3>
<p style="text-align: center;">
Want to see more? Stay tuned, as the project is actively maintained and everything is changing rapidly!

<img style="border: 5px solid #555;" src="https://media.tenor.com/sIzMTGPxIeMAAAAC/well-done.gif" alt="Good Job" width="320px">
</p>