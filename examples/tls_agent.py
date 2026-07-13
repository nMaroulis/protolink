"""Run a ProtoLink HTTPS agent with TLS or mutual TLS.

Create a server certificate for ``127.0.0.1`` or ``localhost`` with your local
CA, then run:

    python examples/tls_agent.py \
        --certfile certs/agent.pem \
        --keyfile certs/agent-key.pem \
        --cafile certs/ca.pem

Add ``--require-client-cert`` to require mutual TLS. For this compact example,
the same certificate identity is used by the agent and client; real deployments
normally issue a separate certificate to each workload.
"""

from __future__ import annotations

import argparse
import socket
from pathlib import Path

from protolink import Agent, AgentCard, Task, TLSConfig, create_llm
from protolink.client import AgentClient
from protolink.transport import HTTPTransport


def find_free_port() -> int:
    """Ask the operating system for an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def parse_args() -> argparse.Namespace:
    """Parse certificate paths and the optional mutual-TLS switch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certfile", type=Path, help="PEM certificate chain")
    parser.add_argument("--keyfile", type=Path, help="PEM private key")
    parser.add_argument("--cafile", type=Path, help="PEM CA bundle")
    parser.add_argument(
        "--require-client-cert",
        action="store_true",
        help="Require a trusted client certificate (mutual TLS)",
    )
    return parser.parse_args()


def main() -> None:
    """Start an HTTPS agent and perform one verified client round trip."""
    args = parse_args()
    if args.certfile is None or args.keyfile is None or args.cafile is None:
        print("Pass --certfile, --keyfile, and --cafile to run the TLS example.")
        return
    agent_url = f"https://127.0.0.1:{find_free_port()}"
    server_tls = TLSConfig(
        certfile=args.certfile,
        keyfile=args.keyfile,
        cafile=args.cafile,
        require_client_cert=args.require_client_cert,
    )
    client_tls = TLSConfig(
        certfile=args.certfile if args.require_client_cert else None,
        keyfile=args.keyfile if args.require_client_cert else None,
        cafile=args.cafile,
    )

    transport = HTTPTransport(
        agent_url,
        tls=server_tls,
        log_level="critical",
        access_log=False,
    )
    agent = Agent(
        AgentCard(name="secure-agent", description="Agent served over HTTPS", url=agent_url),
        transport=transport,
        llm=create_llm("mock", default_response="hello over TLS"),
        verbosity=0,
    )
    client_transport = HTTPTransport(
        "http://127.0.0.1:0",
        tls=client_tls,
        log_level="critical",
        access_log=False,
    )
    client = AgentClient(client_transport)

    try:
        agent.start(register=False, background=True)
        result = client.sync.send_task(agent_url, Task.create_infer(prompt="Say hello securely"))
        print(result.get_last_part_content())
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
