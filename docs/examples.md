# Examples

This section links to example projects and code snippets in the repository.

!!! tip "New here?"
    Start with the **Jupyter Notebooks** in `examples/notebooks/basic_example`! They provide the easiest and best interactive introduction to running the Registry and Agents.

## Jupyter Notebooks (Recommended)

The best way to get started is by running the interactive notebooks located in [`examples/notebooks/basic_example`](https://github.com/nMaroulis/protolink/tree/main/examples/notebooks/basic_example).

These notebooks demonstrate a full multi-agent system with a Registry, a Weather Agent, and an Alert Agent:

- **[`registry.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/registry.ipynb)**: Learn how to set up the Registry service for agent discovery.
- **[`weather_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/weather_agent.ipynb)**: Build an agent that provides data (simulated weather info) and registers itself.
- **[`alert_agent.ipynb`](https://github.com/nMaroulis/protolink/blob/main/examples/notebooks/basic_example/alert_agent.ipynb)**: Build an agent that discovers the weather agent, consumes its data, and sends alerts.

Run them in order to see the agents discover and interact with each other on your local machine.

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


<h3 style="text-align: center;"> 🎉🎉 Congratulations, You made it! 🎉🎉 </h3>
<p style="text-align: center;">
Want to see more? Stay tuned, as the project is actively maintained and everything is changing rapidly! 
<br/>
<img style="border: 5px solid #555;" src="https://media.tenor.com/sIzMTGPxIeMAAAAC/well-done.gif" alt="Good Job" width="320px">
</p>