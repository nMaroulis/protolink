"""Tests for first-party ProtoLink retrieval and Agent integration."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    BudgetEnforcer,
    BudgetExceededError,
    CancellationToken,
    CapabilityPolicy,
    Citation,
    Document,
    Knowledge,
    LocalTraceTelemetry,
    RAGAnswer,
    RunBudget,
    RunContext,
    SearchHit,
    Task,
    create_knowledge,
    create_llm,
)
from protolink.rag import (
    AutoLoader,
    CallableEmbedder,
    CallableRetriever,
    ChromaRetriever,
    HashEmbedder,
    InMemoryVectorStore,
    KnowledgeNotFoundError,
    PineconeRetriever,
    QdrantRetriever,
    RecursiveCharacterSplitter,
    SQLiteVectorStore,
    UnsupportedKnowledgeOperationError,
    VectorStoreRetriever,
)


def _card(name: str = "rag-agent") -> AgentCard:
    return AgentCard(
        name=name,
        description="Answers questions from application knowledge",
        url=f"runtime://{name}",
    )


def test_rag_models_have_stable_ids_and_round_trip() -> None:
    first = Document("A support policy.", source="policy.md", metadata={"team": "support"})
    second = Document("A support policy.", source="policy.md", metadata={"team": "support"})
    assert first.id == second.id
    assert Document.from_dict(first.to_dict()) == first

    hit = SearchHit(
        text="A support policy.",
        score=0.91,
        source="policy.md",
        metadata={"page": 2},
        document_id=first.id,
        chunk_id="chunk_1",
        rank=1,
    )
    citation = Citation.from_hit(hit, 1)
    answer = RAGAnswer(text="See policy [1].", citations=[citation], hits=[hit], query="policy")
    assert RAGAnswer.from_dict(answer.to_dict()) == answer
    assert citation.label == "[1]"
    assert str(answer) == "See policy [1]."
    assert SearchHit(text="safe", score=float("nan")).score is None


def test_recursive_splitter_bounds_chunks_and_preserves_metadata() -> None:
    splitter = RecursiveCharacterSplitter(chunk_size=40, chunk_overlap=8)
    document = Document(
        "First paragraph explains refunds.\n\nSecond paragraph explains exchanges and store credit.",
        source="guide.md",
        metadata={"team": "support"},
    )
    chunks = splitter.split([document])

    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 40 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.source == "guide.md" for chunk in chunks)
    assert all(chunk.metadata["team"] == "support" for chunk in chunks)
    assert chunks == splitter.split([document])


def test_recursive_splitter_overlap_never_drops_source_content() -> None:
    text = "".join(chr(0x400 + index) for index in range(101))
    parts = RecursiveCharacterSplitter(chunk_size=40, chunk_overlap=8).split_text(text)
    rebuilt = parts[0]
    for part in parts[1:]:
        overlap = next(
            (size for size in range(min(len(rebuilt), len(part)), 0, -1) if rebuilt.endswith(part[:size])),
            0,
        )
        rebuilt += part[overlap:]

    assert rebuilt == text
    assert all(len(part) <= 40 for part in parts)


def test_managed_memory_knowledge_lifecycle_and_search_controls(tmp_path: Path) -> None:
    support = tmp_path / "support.md"
    engineering = tmp_path / "engineering.md"
    support.write_text("Customers may request a refund within thirty days.", encoding="utf-8")
    engineering.write_text("Deployments use blue green release slots.", encoding="utf-8")

    knowledge = create_knowledge(
        "memory",
        name="company",
        mode="hybrid",
        mmr_lambda=0.7,
    )
    report = knowledge.sync.add(
        [
            Document(support.read_text(), source=str(support), metadata={"team": "support"}),
            Document(engineering.read_text(), source=str(engineering), metadata={"team": "engineering"}),
        ]
    )
    assert report.documents == 2
    assert report.added == 2

    hits = knowledge.sync.search("refund deadline", where={"team": "support"})
    assert hits
    assert hits[0].source == str(support)
    assert hits[0].metadata["_rag"]["mode"] == "hybrid"
    assert knowledge.sync.search("refund", where={"team": "engineering"}) == []

    replacement = Document(
        "Customers may request a refund within sixty days.",
        source=str(support),
        metadata={"team": "support"},
    )
    replace_report = knowledge.sync.upsert(replacement)
    assert replace_report.deleted == 1
    assert "sixty days" in knowledge.sync.search("refund deadline")[0].text

    deleted = knowledge.sync.delete(sources=[str(engineering)])
    assert deleted == 1
    assert knowledge.sync.search("deployment slots") == []


def test_single_string_source_is_staged_as_one_source(tmp_path: Path) -> None:
    policy = tmp_path / "policy.md"
    policy.write_text("Travel receipts are due after thirty days.", encoding="utf-8")
    knowledge = create_knowledge("memory", sources=str(policy))

    hits = knowledge.sync.search("travel receipt deadline")

    assert hits
    assert hits[0].source == str(policy.resolve())


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_local_search_modes_thresholds_and_fixed_filters(mode: str) -> None:
    knowledge = create_knowledge(
        "memory",
        mode=mode,
        where={"tenant": "alpha"},
    )
    knowledge.sync.add(
        [
            Document(
                "Alpha customers receive a refund after thirty days.",
                source="alpha.md",
                metadata={"tenant": "alpha"},
            ),
            Document(
                "Beta customers receive a refund after ninety days.",
                source="beta.md",
                metadata={"tenant": "beta"},
            ),
        ]
    )

    hits = knowledge.sync.search("customer refund days", where={"tenant": "beta"})

    assert hits
    assert {hit.source for hit in hits} == {"alpha.md"}

    strict = create_knowledge("memory", mode=mode, score_threshold=1.1)
    strict.sync.add_text("A relevant refund policy.", source="strict.md")
    assert strict.sync.search("refund policy") == []


def test_managed_upsert_stages_embeddings_and_replaces_source_atomically() -> None:
    class ToggleEmbedder:
        def __init__(self) -> None:
            self.delegate = HashEmbedder(dimensions=32)
            self.fail_documents = False

        async def embed_documents(self, texts):
            if self.fail_documents:
                raise RuntimeError("embedding failed")
            return await self.delegate.embed_documents(texts)

        async def embed_query(self, text):
            return await self.delegate.embed_query(text)

    embedder = ToggleEmbedder()
    store = InMemoryVectorStore()
    knowledge = create_knowledge("vector", store=store, embedder=embedder)
    knowledge.sync.upsert(Document("The old warranty is valid.", source="warranty.md"))
    embedder.fail_documents = True

    with pytest.raises(RuntimeError, match="embedding failed"):
        knowledge.sync.upsert(Document("The new warranty is valid.", source="warranty.md"))

    assert "old warranty" in knowledge.sync.search("old warranty")[0].text.lower()

    embedder.fail_documents = False
    knowledge.sync.upsert(Document("Version one policy.", id="policy"))
    knowledge.sync.upsert(Document("Version two policy.", id="policy"))
    assert len(store) == 2  # warranty plus the one stable, source-less policy
    assert "version two" in knowledge.sync.search("version two")[0].text.lower()


@pytest.mark.asyncio
async def test_lazy_ready_waits_for_concurrent_initialization_and_survives_cancellation() -> None:
    class Loader:
        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def load(self, source, *, metadata=None):
            self.calls += 1
            self.started.set()
            if self.calls == 1:
                await self.release.wait()
            return [Document("Concurrent initialization is safe.", source=str(source))]

    loader = Loader()
    knowledge = create_knowledge("memory", sources="logical-source", loader=loader)
    pending_action = await knowledge.as_tool().prepare_action(
        {"query": "initialization", "k": 5, "where": None},
        RunContext(),
    )
    assert "knowledge.index" in pending_action.capabilities
    first = asyncio.create_task(knowledge.search("initialization"))
    await loader.started.wait()
    second = asyncio.create_task(knowledge.search("initialization"))
    await asyncio.sleep(0)
    assert not second.done()
    loader.release.set()
    first_hits, second_hits = await asyncio.gather(first, second)
    assert first_hits and second_hits
    assert loader.calls == 1
    ready_action = await knowledge.as_tool().prepare_action(
        {"query": "initialization", "k": 5, "where": None},
        RunContext(),
    )
    assert "knowledge.index" not in ready_action.capabilities

    canceled_loader = Loader()
    canceled = create_knowledge("memory", sources="retry-source", loader=canceled_loader)
    initialization = asyncio.create_task(canceled.ready())
    await canceled_loader.started.wait()
    initialization.cancel()
    with pytest.raises(asyncio.CancelledError):
        await initialization
    retry_report = await canceled.ready()
    assert retry_report.added == 1
    assert canceled_loader.calls == 2


@pytest.mark.asyncio
async def test_url_loader_rejects_private_network_targets() -> None:
    with pytest.raises(ValueError, match="non-public"):
        await AutoLoader().load("http://127.0.0.1/internal")


@pytest.mark.asyncio
async def test_sync_retriever_and_embedder_functions_do_not_block_event_loop() -> None:
    def slow_retrieve(query: str):
        time.sleep(0.1)
        return [query]

    def slow_embed(texts):
        time.sleep(0.1)
        return [[1.0, 0.0] for _ in texts]

    retrieve_task = asyncio.create_task(CallableRetriever(slow_retrieve).retrieve("hello"))
    await asyncio.sleep(0.02)
    assert not retrieve_task.done()
    assert (await retrieve_task)[0].text == "hello"

    embed_task = asyncio.create_task(CallableEmbedder(slow_embed).embed_documents(["hello"]))
    await asyncio.sleep(0.02)
    assert not embed_task.done()
    assert await embed_task == [[1.0, 0.0]]


@pytest.mark.asyncio
async def test_vector_store_retriever_uses_its_configured_default_k() -> None:
    observed: dict[str, Any] = {}

    class Store:
        async def search(self, **kwargs):
            observed.update(kwargs)
            return []

    retriever = VectorStoreRetriever(
        Store(),
        HashEmbedder(dimensions=16),
        default_k=2,
    )
    assert await retriever.retrieve("policy") == []
    assert observed["k"] == 2


def test_refresh_can_remove_sources_missing_from_a_complete_directory(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("Alpha handbook material.", encoding="utf-8")
    second.write_text("Beta handbook material.", encoding="utf-8")
    knowledge = create_knowledge("memory")

    initial = knowledge.sync.refresh(tmp_path, delete_missing=True)
    assert initial.documents == 2
    second.unlink()
    refreshed = knowledge.sync.refresh(tmp_path, delete_missing=True)

    assert refreshed.deleted >= 2
    assert knowledge.sync.search("Beta") == []
    assert knowledge.sync.search("Alpha handbook")


def test_sqlite_store_persists_across_knowledge_instances(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.db"
    first = create_knowledge("sqlite", path=path, namespace="support")
    first.sync.add_text("Warranty coverage lasts two years.", source="warranty.md")

    second = create_knowledge("sqlite", path=path, namespace="support")
    hits = second.sync.search("warranty years")
    assert hits
    assert hits[0].source == "warranty.md"
    assert isinstance(second.store, SQLiteVectorStore)


@pytest.mark.asyncio
async def test_callable_retrievers_normalize_sync_async_and_mapping_results() -> None:
    def sync_search(query: str, *, k: int, where: dict[str, Any] | None):
        assert query == "refund"
        assert k == 2
        assert where == {"team": "support"}
        return [
            {"content": "Thirty days.", "score": 0.9, "source": "policy.md"},
            "Store credit is also available.",
        ]

    async def async_search(query: str):
        return [SearchHit(text=f"Result for {query}")]

    sync_hits = await CallableRetriever(sync_search).retrieve(
        "refund",
        k=2,
        where={"team": "support"},
    )
    async_hits = await CallableRetriever(async_search).retrieve("shipping", k=1)

    assert [hit.rank for hit in sync_hits] == [1, 2]
    assert sync_hits[0].source == "policy.md"
    assert async_hits[0].text == "Result for shipping"


@pytest.mark.asyncio
async def test_retrieval_only_knowledge_rejects_index_lifecycle() -> None:
    knowledge = Knowledge.from_callable(lambda query: [f"Result for {query}"])
    assert (await knowledge.search("hello"))[0].text == "Result for hello"
    with pytest.raises(UnsupportedKnowledgeOperationError):
        await knowledge.add_text("Cannot index this")


@pytest.mark.asyncio
async def test_knowledge_tool_is_typed_bounded_and_policy_labeled() -> None:
    knowledge = create_knowledge(
        "memory",
        name="product docs",
        description="internal product documentation",
        context_max_chars=12,
    )
    await knowledge.add_text("A long product description for retrieval.", source="product.md")
    tool = knowledge.as_tool()
    result = await tool(query="product description", k=3)

    assert tool.name == "search_product_docs"
    assert tool.capabilities == ("knowledge.read", "knowledge.product_docs.read")
    assert tool.input_schema["required"] == ["query"]
    assert "instructions" in tool.output_schema["properties"]
    assert set(tool.output_schema["required"]) <= set(result)
    assert set(result) <= set(tool.output_schema["properties"])
    assert result["knowledge"] == "product docs"
    assert result["hits"][0]["citation"] == "[product_docs:1]"
    assert len(result["hits"][0]["text"]) <= 12


@pytest.mark.asyncio
async def test_existing_vector_database_adapters_normalize_sdk_shapes() -> None:
    embedder = HashEmbedder(dimensions=16)

    class ChromaCollection:
        def query(self, **kwargs):
            assert kwargs["query_texts"] == ["refund"]
            return {
                "ids": [["c1"]],
                "documents": [["Thirty days."]],
                "metadatas": [[{"source": "policy.md"}]],
                "distances": [[0.25]],
            }

    class PineconeIndex:
        def query(self, **kwargs):
            assert kwargs["top_k"] == 2
            assert kwargs["filter"] == {"team": "support"}
            return {
                "matches": [
                    {
                        "id": "p1",
                        "score": 0.88,
                        "metadata": {"text": "Thirty days.", "source": "policy.md"},
                    }
                ]
            }

    class QdrantClient:
        def query_points(self, **kwargs):
            assert kwargs["collection_name"] == "docs"
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id="q1",
                        score=0.87,
                        payload={"text": "Thirty days.", "source": "policy.md"},
                    )
                ]
            )

    chroma = await ChromaRetriever(ChromaCollection()).retrieve("refund", k=1)
    pinecone = await PineconeRetriever(PineconeIndex(), embedder).retrieve(
        "refund",
        k=2,
        where={"team": "support"},
    )
    qdrant = await QdrantRetriever(QdrantClient(), "docs", embedder).retrieve("refund", k=1)

    assert chroma[0].chunk_id == "c1"
    assert pinecone[0].score == 0.88
    assert qdrant[0].source == "policy.md"


def test_agent_attaches_knowledge_as_an_advertised_tool() -> None:
    knowledge = create_knowledge("memory", name="product_docs")
    agent = Agent(_card(), knowledge=knowledge, verbosity=0)

    assert agent.knowledge == {"product_docs": knowledge}
    assert "search_product_docs" in agent.tools
    assert agent.card.capabilities.rag is True
    assert agent.card.capabilities.tool_calling is True
    assert any(skill.id == "search_product_docs" for skill in agent.card.skills)
    prompt_metadata = json.loads(agent._build_tools_prompt())
    assert prompt_metadata[0]["capabilities"] == [
        "knowledge.product_docs.read",
        "knowledge.read",
    ]


def test_agent_rejects_knowledge_tool_collisions() -> None:
    agent = Agent(_card(), verbosity=0)

    @agent.tool(name="search_knowledge", description="Existing tool")
    async def existing_tool() -> str:
        return "existing"

    with pytest.raises(ValueError, match="conflicts"):
        agent.add_knowledge(create_knowledge("memory"))

    attached = Agent(_card("attached"), knowledge=create_knowledge("memory"), verbosity=0)
    with pytest.raises(ValueError, match="cannot be replaced"):

        @attached.tool(name="search_knowledge", description="Replacement tool")
        async def replacement_tool() -> str:
            return "replacement"


def test_agentic_infer_calls_knowledge_tool_and_observes_retrieved_passages() -> None:
    knowledge = create_knowledge("memory", description="support policies")
    knowledge.sync.add_text("Refund requests are accepted within thirty days.", source="policy.md")
    observations: list[dict[str, Any]] = []

    def respond(history, system_prompt):
        assert "search_knowledge" in system_prompt
        for message in history.messages:
            if message["role"] != "system":
                continue
            try:
                payload = json.loads(message["content"])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("type") == "tool_result":
                observations.append(payload)
                passage = payload["result"]["hits"][0]["text"]
                return {"type": "final", "content": f"{passage} [1]"}
        return {
            "type": "tool_call",
            "tool": "search_knowledge",
            "args": {"query": "refund request deadline"},
        }

    agent = Agent(
        _card(),
        transport="runtime",
        llm=create_llm("mock", response_callback=respond),
        knowledge=knowledge,
        verbosity=0,
    )
    answer = agent.sync.invoke("When can I request a refund?")

    assert answer == "Refund requests are accepted within thirty days. [1]"
    assert observations[0]["tool"] == "search_knowledge"


def test_agent_ask_retrieves_before_first_model_action_and_returns_citations() -> None:
    knowledge = create_knowledge("memory", name="policies")
    knowledge.sync.add_text("Support is available from 08:00 to 18:00.", source="hours.md")

    def respond(history, _system_prompt):
        user_messages = [message["content"] for message in history.messages if message["role"] == "user"]
        assert "<retrieved-knowledge>" in user_messages[-1]
        assert "Support is available from 08:00 to 18:00." in user_messages[-1]
        return {"type": "final", "content": "Support runs from 08:00 to 18:00 [1]."}

    agent = Agent(
        _card(),
        transport="runtime",
        llm=create_llm("mock", response_callback=respond),
        knowledge=knowledge,
        verbosity=0,
    )
    answer = agent.sync.ask("When is support available?")

    assert isinstance(answer, RAGAnswer)
    assert answer.text.endswith("[1].")
    assert answer.citations[0].source == "hours.md"
    assert answer.hits[0].text.startswith("Support is available")


def test_always_and_required_retrieval_modes_apply_to_normal_infer_tasks() -> None:
    knowledge = create_knowledge("memory")
    knowledge.sync.add_text("The release train departs on Tuesday.", source="release.md")

    def answer_with_context(history, _system_prompt):
        user = [message["content"] for message in history.messages if message["role"] == "user"][-1]
        assert "release train departs on Tuesday" in user
        return {"type": "final", "content": "Tuesday [1]."}

    always_agent = Agent(
        _card("always-agent"),
        transport="runtime",
        llm=create_llm("mock", response_callback=answer_with_context),
        knowledge=knowledge,
        retrieval="always",
        verbosity=0,
    )
    assert always_agent.sync.invoke("When does the release train depart?") == "Tuesday [1]."

    empty = create_knowledge("memory")
    required_agent = Agent(
        _card("required-agent"),
        transport="runtime",
        llm=create_llm("mock", default_response="must not run"),
        knowledge=empty,
        retrieval="required",
        verbosity=0,
    )
    with pytest.raises(KnowledgeNotFoundError):
        required_agent.sync.invoke("Unknown internal fact")

    missing_agent = Agent(
        _card("missing-agent"),
        transport="runtime",
        llm=create_llm("mock", default_response="must not run"),
        retrieval="required",
        verbosity=0,
    )
    with pytest.raises(KnowledgeNotFoundError):
        missing_agent.sync.invoke("Unknown internal fact")


def test_retriever_decorator_and_serialization_descriptor() -> None:
    agent = Agent(_card(), retrieval="auto", verbosity=0)

    @agent.retriever(name="custom", description="application-owned custom records")
    async def custom_search(query: str, *, k: int = 5):
        return [SearchHit(text=f"{query}:{k}", source="custom")]

    result = asyncio.run(agent.call_tool("search_custom", query="hello", k=2))
    serialized = agent.to_dict()

    assert result["hits"][0]["text"] == "hello:2"
    assert "tools" not in serialized
    assert serialized["knowledge"][0]["name"] == "custom"
    assert serialized["knowledge"][0]["reconnect_required"] is True
    with pytest.raises(ValueError, match="Pass knowledge"):
        Agent.from_dict(serialized)

    restored = Agent.from_dict(serialized, knowledge=agent.knowledge["custom"], verbosity=0)
    assert "search_custom" in restored.tools

    wrong = Knowledge.from_callable(lambda query: [query], name="other")
    with pytest.raises(ValueError, match="exactly match"):
        Agent.from_dict(serialized, knowledge=wrong, verbosity=0)


def test_serialization_preserves_and_strictly_validates_retrieval_mode() -> None:
    agent = Agent(_card("serialized-required"), retrieval="required", verbosity=0)
    serialized = agent.to_dict()

    assert serialized["retrieval"] == "required"
    assert Agent.from_dict(serialized, verbosity=0).retrieval == "required"
    with pytest.raises(ValueError, match="retrieval must"):
        Agent.from_dict(serialized, retrieval="requried", verbosity=0)


def test_factory_rejects_silently_ignored_external_controls() -> None:
    class Collection:
        def query(self, **kwargs):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    with pytest.raises(ValueError, match="vector retrieval only"):
        create_knowledge("chroma", collection=Collection(), mode="hybrid")
    with pytest.raises(TypeError, match="does not implement"):
        create_knowledge("chroma", collection=Collection(), fetch_k=20)
    with pytest.raises(TypeError, match="retrieval-only"):
        create_knowledge(
            "chroma",
            collection=Collection(),
            loader=AutoLoader(),
        )
    with pytest.raises(ValueError, match="MMR candidate pool"):
        create_knowledge("memory", fetch_k=20)


@pytest.mark.asyncio
async def test_qdrant_named_vector_and_filter_converter_are_forwarded() -> None:
    sentinel = object()

    class Client:
        def query_points(self, **kwargs):
            assert kwargs["using"] == "content"
            assert kwargs["query_filter"] is sentinel
            return SimpleNamespace(points=[])

    retriever = QdrantRetriever(
        Client(),
        "docs",
        HashEmbedder(dimensions=16),
        vector_name="content",
        filter_converter=lambda where: sentinel,
    )
    assert await retriever.retrieve("hello", where={"tenant": "alpha"}) == []


def test_agent_level_retrieval_cannot_be_downgraded_by_task_metadata() -> None:
    empty = create_knowledge("memory")
    agent = Agent(
        _card("monotonic-required"),
        llm=create_llm("mock", default_response="must not run"),
        knowledge=empty,
        retrieval="required",
        verbosity=0,
    )
    task = Task.create_infer(
        prompt="Answer without evidence",
        metadata={"retrieval": "auto"},
    )

    with pytest.raises(KnowledgeNotFoundError):
        asyncio.run(agent.handle_task(task))


@pytest.mark.asyncio
async def test_deterministic_retrieval_honors_policy_cancellation_and_budget_preflight() -> None:
    calls = 0

    async def retrieve(query: str):
        nonlocal calls
        calls += 1
        return [SearchHit(text=f"Evidence for {query}")]

    knowledge = Knowledge.from_callable(retrieve, name="private")
    denied = Agent(
        _card("denied-rag"),
        llm=create_llm("mock", default_response="must not run"),
        knowledge=knowledge,
        retrieval="always",
        policy=CapabilityPolicy({"knowledge.private.read": "deny"}),
        verbosity=0,
    )
    with pytest.raises(ActionDeniedError):
        await denied.handle_task(Task.create_infer(prompt="private fact"))
    assert calls == 0

    token = CancellationToken()

    async def cancel_during_approval(_request, _context):
        token.cancel("scope expired")
        return True

    approval_agent = Agent(
        _card("approval-rag"),
        llm=create_llm("mock", default_response="must not run"),
        knowledge=knowledge,
        retrieval="always",
        policy=CapabilityPolicy({"knowledge.private.read": "require_approval"}),
        approval_handler=cancel_during_approval,
        verbosity=0,
    )
    approval_task = Task.create_infer(prompt="private fact")
    infer_part = approval_task.get_last_item().parts[0]
    with pytest.raises(asyncio.CancelledError):
        await approval_agent.call_llm(
            infer_part,
            task=approval_task,
            cancellation_token=token,
        )
    assert calls == 0

    budget_agent = Agent(
        _card("budget-rag"),
        llm=create_llm("mock", default_response="must not run"),
        knowledge=knowledge,
        retrieval="always",
        verbosity=0,
    )
    budget = BudgetEnforcer(RunBudget(max_steps=0))
    budget_task = Task.create_infer(prompt="private fact")
    with pytest.raises(BudgetExceededError):
        await budget_agent.call_llm(
            budget_task.get_last_item().parts[0],
            task=budget_task,
            budget_enforcer=budget,
        )
    assert budget.usage.tool_calls == 0
    assert calls == 0


@pytest.mark.asyncio
async def test_deterministic_retrieval_streams_action_lifecycle_events() -> None:
    knowledge = create_knowledge("memory")
    await knowledge.add_text("The release happens on Tuesday.", source="release.md")
    agent = Agent(
        _card("streamed-rag"),
        llm=create_llm("mock", default_response="Tuesday [1]."),
        knowledge=knowledge,
        retrieval="always",
        verbosity=0,
    )
    task = Task.create_infer(prompt="When is the release?")
    events = [event async for event in agent.handle_task_streaming(task)]
    event_types = [event.llm_event_type for event in events if hasattr(event, "llm_event_type")]

    for expected in ("action_requested", "policy_decision", "tool_start", "tool_result"):
        assert expected in event_types
    assert event_types.index("tool_result") < event_types.index("llm_step")
    tool_result = next(event for event in events if getattr(event, "llm_event_type", None) == "tool_result")
    assert tool_result.metadata["result_omitted"] is True
    assert any(artifact.kind == "action_result" for artifact in task.artifacts)


@pytest.mark.asyncio
async def test_rag_evidence_is_ephemeral_and_sources_are_private_in_traces_and_tasks() -> None:
    secret_text = "CONFIDENTIAL-CONTEXT: the launch code is violet."
    secret_source = "/private/company/signed-launch-plan.md?token=secret"
    knowledge = create_knowledge("memory")
    await knowledge.add_text(secret_text, source=secret_source)
    telemetry = LocalTraceTelemetry()
    agent = Agent(
        _card("private-trace-rag"),
        llm=create_llm("mock", default_response="The code is violet [1]."),
        knowledge=knowledge,
        retrieval="always",
        telemetry=telemetry,
        state=["conversation"],
        verbosity=0,
    )
    task = Task.create_infer(prompt="What is the launch code?")
    await agent.handle_task(task)

    history = json.dumps(agent.llm.history.messages)
    task_payload = json.dumps(task.to_dict())
    trace = telemetry.recorder.replay()[0]
    trace_payload = json.dumps(trace)
    tool_spans = [span for span in trace["spans"] if span["kind"] == "tool"]

    assert "What is the launch code?" in history
    assert secret_text not in history
    assert secret_source not in history
    assert secret_source not in task_payload
    assert secret_text not in trace_payload
    assert secret_source not in trace_payload
    assert len(tool_spans) == 1


@pytest.mark.asyncio
async def test_auto_retrieval_evidence_is_visible_only_to_the_active_model_loop() -> None:
    secret_text = "CONFIDENTIAL launch evidence: the sealed phrase is violet-orbit."
    secret_source = "/private/launch-evidence.md?access_token=secret"
    knowledge = create_knowledge("memory", name="private_auto")
    await knowledge.add_text(secret_text, source=secret_source)
    telemetry = LocalTraceTelemetry()
    model_saw_secret = False
    follow_up_histories: list[str] = []

    def respond(history, _system_prompt):
        nonlocal model_saw_secret
        serialized = json.dumps(history.messages)
        last_user = [message["content"] for message in history.messages if message["role"] == "user"][-1]
        if last_user == "Is there confidential launch evidence?":
            if secret_text in serialized:
                model_saw_secret = True
                return {
                    "type": "final",
                    "content": "The authorized evidence was found [private_auto:1].",
                }
            return {
                "type": "tool_call",
                "tool": "search_private_auto",
                "args": {"query": "confidential launch evidence"},
            }
        follow_up_histories.append(serialized)
        return {"type": "final", "content": "The follow-up history is clean."}

    agent = Agent(
        _card("private-auto-rag"),
        llm=create_llm("mock", response_callback=respond),
        knowledge=knowledge,
        retrieval="auto",
        telemetry=telemetry,
        state=["conversation"],
        verbosity=0,
    )
    first = Task.create_infer(prompt="Is there confidential launch evidence?")
    first.metadata["session_id"] = "shared-private-session"
    await agent.handle_task(first)

    persisted_history = json.dumps(agent.llm.history.to_list())
    trace = next(item for item in telemetry.recorder.replay() if item["task_id"] == first.id)
    trace_payload = json.dumps(trace)
    task_payload = json.dumps(first.to_dict())
    tool_events = [event for event in trace["events"] if event["type"] == "tool_result"]

    assert model_saw_secret is True
    assert secret_text not in persisted_history
    assert secret_source not in persisted_history
    assert secret_text not in trace_payload
    assert secret_source not in trace_payload
    assert secret_text not in task_payload
    assert secret_source not in task_payload
    assert tool_events[0]["payload"]["result_omitted"] is True
    assert tool_events[0]["payload"]["result"]["hit_count"] == 1
    assert tool_events[0]["payload"]["result"]["source_ids"]
    assert len([span for span in trace["spans"] if span["kind"] == "tool"]) == 1

    follow_up = Task.create_infer(prompt="Continue without reusing prior evidence.")
    follow_up.metadata["session_id"] = "shared-private-session"
    await agent.handle_task(follow_up)
    assert follow_up_histories
    assert secret_text not in follow_up_histories[0]
    assert secret_source not in follow_up_histories[0]


def test_required_mode_needs_model_visible_evidence() -> None:
    knowledge = create_knowledge("memory", context_max_chars=1)
    knowledge.sync.add_text("A real passage exists.", source="tiny.md")
    model_called = False

    def respond(_history, _system_prompt):
        nonlocal model_called
        model_called = True
        return {"type": "final", "content": "ungrounded"}

    agent = Agent(
        _card("visible-required"),
        llm=create_llm("mock", response_callback=respond),
        knowledge=knowledge,
        retrieval="required",
        verbosity=0,
    )

    with pytest.raises(KnowledgeNotFoundError):
        agent.sync.invoke("What does the passage say?")
    assert model_called is False


def test_multi_knowledge_ask_allocates_context_and_returns_global_citations() -> None:
    first = create_knowledge("memory", name="policies", context_max_chars=500)
    second = create_knowledge("memory", name="handbook", context_max_chars=500)
    first.sync.add_text("Refunds are accepted for thirty days.", source="refund.md")
    second.sync.add_text("Support opens at eight o'clock.", source="support.md")

    def respond(history, system_prompt):
        user = [message["content"] for message in history.messages if message["role"] == "user"][-1]
        assert "Refunds are accepted" in user
        assert "Support opens" in user
        assert "[1]" in user and "[2]" in user
        assert "search_policies" not in system_prompt
        assert "search_handbook" not in system_prompt
        return {"type": "final", "content": "Refunds: 30 days [1]. Support: 08:00 [2]."}

    agent = Agent(
        _card("multi-rag"),
        llm=create_llm("mock", response_callback=respond),
        knowledge=[first, second],
        verbosity=0,
    )
    answer = agent.sync.ask("Summarize refunds and support hours.")

    assert [citation.number for citation in answer.citations] == [1, 2]
    assert [citation.source for citation in answer.citations] == ["refund.md", "support.md"]
