"""
ProtoLink v0.3.0 Example: OAuth 2.0 Delegated Scopes & Enterprise Auth

This example demonstrates v0.3.0 security features:
- Bearer token authentication
- OAuth 2.0 delegated scopes
- Skill-based authorization
- Multi-org agent communication

Run with:
    python oauth_agent_example.py
"""

import asyncio

from protolink.agent import Agent
from protolink.models import AgentCard, Message, Task
from protolink.security import APIKeyAuth, AuthContext, BearerTokenAuth
from protolink.transport import RuntimeTransport


class SecureAnalysisAgent(Agent):
    """Agent with security and authorization."""

    def __init__(self, auth_provider=None):
        # NEW in v0.3.0: Include security schemes in AgentCard
        card = AgentCard(
            name="secure-analysis",
            description="Secure analysis agent with authorization",
            url="local://secure-analysis",
            capabilities={"streaming": True, "tasks": True},
            security_schemes={  # NEW in v0.3.0
                "bearer": {"type": "bearer", "description": "JWT Bearer token authentication"},
                "oauth2": {"type": "oauth2", "description": "OAuth 2.0 delegated scopes"},
            },
            required_scopes=["skill:analyze"],  # NEW in v0.3.0
        )
        super().__init__(card, auth_provider=auth_provider)

    def handle_task(self, task: Task) -> Task:
        """Process task (requires authorization)."""
        user_text = task.messages[0].parts[0].content

        # Check if we have auth context (set by verify_request_auth)
        if self.auth_provider and not self._auth_context:
            raise PermissionError("Authentication required")

        # Show authenticated user/principal
        if self._auth_context:
            principal = self._auth_context.principal_id
            scopes = self._auth_context.scopes
            response = f"Analyzed by {principal} with scopes {scopes}: {user_text}"
        else:
            response = f"Analyzed (no auth): {user_text}"

        return task.complete(response)


async def example_bearer_token():
    """Bearer token authentication example."""
    print("\n=== v0.3.0: Bearer Token Auth ===\n")

    # Create agent with Bearer token auth
    bearer_auth = BearerTokenAuth(secret="my-secret", algorithm="HS256")
    agent = SecureAnalysisAgent(auth_provider=bearer_auth)
    transport = RuntimeTransport()
    transport.register_agent(agent)

    # Create a task
    task = Task.create(Message.user("Analyze this data"))

    # Simulate receiving a request with Bearer token
    bearer_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsInNjb3BlcyI6WyJza2lsbDphbmFseXplIl19.signature"
    )

    try:
        # Verify auth before processing
        auth_context = await agent.verify_request_auth(f"Bearer {bearer_token}", skill="analyze")
        print("✅ Authentication successful!")
        print(f"   Principal: {auth_context.principal_id}")
        print(f"   Scopes: {auth_context.scopes}")

        # Process task with auth context
        result = agent.handle_task(task)
        print("\n✅ Task completed:")
        print(f"   {result.messages[-1].parts[0].content}")
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_oauth2_delegation():
    """OAuth 2.0 delegated scopes example."""
    print("\n=== v0.3.0: OAuth 2.0 Delegation ===\n")

    # In real scenario, this would call an OAuth endpoint
    # For demo, we'll use mock auth
    class MockOAuth2Auth:
        async def authenticate(self, token):
            # Simulate token exchange
            return AuthContext(
                principal_id="org-abc:user-xyz", token="delegated-token", scopes=["skill:analyze", "data:read"]
            )

        async def authorize(self, context, skill):
            required = f"skill:{skill}"
            return required in context.scopes

    oauth_auth = MockOAuth2Auth()
    agent = SecureAnalysisAgent(auth_provider=oauth_auth)
    transport = RuntimeTransport()
    transport.register_agent(agent)

    # Simulate OAuth token exchange
    user_token = "user-token-from-browser"

    try:
        # Verify delegated auth
        auth_context = await agent.verify_request_auth(f"Bearer {user_token}", skill="analyze")
        print("✅ OAuth 2.0 delegation successful!")
        print(f"   Principal: {auth_context.principal_id}")
        print(f"   Delegated scopes: {auth_context.scopes}")

        # Process task
        task = Task.create(Message.user("Process org data"))
        result = agent.handle_task(task)
        print("\n✅ Task completed:")
        print(f"   {result.messages[-1].parts[0].content}")
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_api_key_auth():
    """API key authentication for service-to-service."""
    print("\n=== v0.3.0: API Key Auth (Service-to-Service) ===\n")

    # Create API key auth with allowed keys
    api_key_auth = APIKeyAuth(
        valid_keys={
            "sk-prod-abc123": ["skill:analyze", "skill:execute"],
            "sk-test-xyz789": ["skill:analyze"],  # Test key with limited scopes
        }
    )

    agent = SecureAnalysisAgent(auth_provider=api_key_auth)  # noqa: F841

    # Test with prod key
    print("Testing with prod API key:")
    try:
        prod_context = await api_key_auth.authenticate("sk-prod-abc123")
        print(f"✅ Prod key authenticated: {prod_context.principal_id}")
        print(f"   Scopes: {prod_context.scopes}")

        # Check authorization
        can_execute = await api_key_auth.authorize(prod_context, "execute")
        print(f"   Can execute: {can_execute}")
    except Exception as e:
        print(f"❌ Error: {e}")

    # Test with test key
    print("\nTesting with test API key:")
    try:
        test_context = await api_key_auth.authenticate("sk-test-xyz789")
        print(f"✅ Test key authenticated: {test_context.principal_id}")
        print(f"   Scopes: {test_context.scopes}")

        # Check authorization
        can_execute = await api_key_auth.authorize(test_context, "execute")
        print(f"   Can execute: {can_execute} (should be False)")
    except Exception as e:
        print(f"❌ Error: {e}")


async def example_transport_with_auth():
    """Using authenticated transport for remote calls."""
    print("\n=== v0.3.0: Transport with Authentication ===\n")

    from protolink import JSONRPCTransport

    # Create agent with auth
    bearer_auth = BearerTokenAuth()
    agent = SecureAnalysisAgent(auth_provider=bearer_auth)  # noqa: F841

    # Create authenticated transport
    transport = JSONRPCTransport(auth_provider=bearer_auth)  # noqa: F841

    print("Transport created with auth provider")
    print(f"  Auth provider: {type(bearer_auth).__name__}")

    # In real scenario, would call:
    # await transport.authenticate(user_token)
    # result = await transport.send_task(remote_agent_url, task, skill="analyze")

    print("✅ Ready to make authenticated remote calls")


async def example_agent_card_discovery():
    """Discover agent security requirements via AgentCard."""
    print("\n=== v0.3.0: Agent Card Discovery ===\n")

    agent = SecureAnalysisAgent()
    card = agent.get_agent_card()

    print(f"Agent: {card.name}")
    print(f"Description: {card.description}")
    print(f"Capabilities: {card.capabilities}")
    print(f"Required scopes: {card.required_scopes}")
    print("\nSecurity schemes:")
    for scheme_name, scheme_info in card.security_schemes.items():
        print(f"  - {scheme_name}: {scheme_info['description']}")

    # Export as JSON (for /.well-known/agent.json)
    print("\nAs JSON (for discovery):")
    import json

    print(json.dumps(card.to_json(), indent=2))


async def main():
    """Run all examples."""
    print("=" * 60)
    print("ProtoLink v0.3.0: Enterprise Authentication Examples")
    print("=" * 60)

    # Run examples
    await example_bearer_token()
    await example_oauth2_delegation()
    await example_api_key_auth()
    await example_transport_with_auth()
    await example_agent_card_discovery()

    print("\n" + "=" * 60)
    print("✅ All v0.3.0 security examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
