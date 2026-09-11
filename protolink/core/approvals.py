"""Application-independent approval lifecycle with optional durable inspection."""

from __future__ import annotations

import asyncio
import copy
import math
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any, Literal

from protolink.core.policy import ApprovalDecision, ApprovalRequest
from protolink.core.run_context import RunContext
from protolink.storage.base import Storage

ApprovalStatus = Literal["pending", "approved", "denied", "canceled", "expired", "uncertain"]


@dataclass(frozen=True)
class ApprovalScope:
    """Run IDs an authenticated application adapter permits a caller to access.

    Construct this from trusted server-side identity/authorization information;
    never accept the scope itself from an untrusted UI request. A fingerprint
    correlates a decision but does not authenticate its sender.
    """

    run_ids: frozenset[str]

    def __post_init__(self) -> None:
        """Copy allowed IDs so later application mutation cannot expand access."""
        object.__setattr__(self, "run_ids", frozenset(self.run_ids))


@dataclass(frozen=True)
class ApprovalRecord:
    """Snapshot for adapters; approval never implies that an effect executed."""

    request: ApprovalRequest
    fingerprint: str
    status: ApprovalStatus
    expires_at: float | None = None
    decision: ApprovalDecision | None = None
    effect_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Serialize a reconnectable record without any executable continuation."""
        return {
            "request": self.request.to_dict(),
            "fingerprint": self.fingerprint,
            "status": self.status,
            "expires_at": self.expires_at,
            "decision": self.decision.to_dict() if self.decision else None,
            "effect_state": self.effect_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRecord:
        """Load an inspection record; a broker separately marks orphan waits uncertain."""
        return cls(
            request=ApprovalRequest.from_dict(data["request"]),
            fingerprint=data["fingerprint"],
            status=data["status"],
            expires_at=data.get("expires_at"),
            decision=ApprovalDecision.from_dict(data["decision"]) if data.get("decision") else None,
            effect_state=data.get("effect_state", "unknown"),
        )


@dataclass(frozen=True)
class ApprovalResolution:
    """Predictable control-plane outcome, including harmless repeat decisions."""

    request_id: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the adapter result."""
        return asdict(self)


class ApprovalBroker:
    """An ``ApprovalHandler`` that waits for decisions from application adapters.

    One broker owns one Storage namespace and runs on one event loop. Storage
    saves precede unblocking the action. Reconnecting clients use ``pending`` or
    ``events`` on the same broker. Reopening durable storage is inspection only:
    orphan pending requests become uncertain and cannot resume execution.
    Stored requests may contain secrets; use a protected, dedicated namespace.
    """

    def __init__(self, *, storage: Storage | None = None, timeout_seconds: float | None = None) -> None:
        """Load optional records and configure a default approval expiration."""
        if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be finite and positive")
        self.storage = storage
        self.timeout_seconds = timeout_seconds
        self._records: dict[str, ApprovalRecord] = {}
        self._waiters: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._subscribers: set[asyncio.Queue[ApprovalRecord]] = set()
        if storage is not None:
            for key, value in (storage.load() or {}).items():
                record = ApprovalRecord.from_dict(value)
                if record.status == "pending":
                    record = self._updated(record, status="uncertain")
                self._records[key] = record
            self._save()

    @staticmethod
    def _updated(record: ApprovalRecord, **changes: Any) -> ApprovalRecord:
        from dataclasses import replace

        return replace(record, **changes)

    def _save(self) -> None:
        if self.storage is not None:
            self.storage.save({key: record.to_dict() for key, record in self._records.items()})

    def _commit(self, record: ApprovalRecord) -> None:
        key = record.request.request_id
        previous = self._records.get(key)
        self._records[key] = record
        try:
            self._save()
        except BaseException:
            if previous is None:
                self._records.pop(key, None)
            else:
                self._records[key] = previous
            raise
        for queue in self._subscribers:
            queue.put_nowait(copy.deepcopy(record))

    async def __call__(self, request: ApprovalRequest, context: RunContext) -> ApprovalDecision:
        """Track a fresh request and unblock on a decision, expiry, or task cancellation."""
        if request.run_id != context.run_id:
            raise ValueError("Approval request does not belong to this run")
        if context.canceled:
            raise asyncio.CancelledError(context.cancel_reason)
        if request.request_id in self._records:
            raise ValueError("Approval request ID has already been used; execution cannot be replayed")
        record = ApprovalRecord(
            request=copy.deepcopy(request),
            fingerprint=request.action.fingerprint,
            status="pending",
            expires_at=time.time() + self.timeout_seconds if self.timeout_seconds is not None else None,
        )
        future: asyncio.Future[ApprovalDecision] = asyncio.get_running_loop().create_future()
        self._waiters[request.request_id] = future
        try:
            self._commit(record)
            try:
                return await asyncio.wait_for(asyncio.shield(future), self.timeout_seconds)
            except TimeoutError:
                decision = ApprovalDecision(approved=False, request_id=request.request_id, reason="Approval expired")
                self._commit(self._updated(self._records[request.request_id], status="expired", decision=decision))
                return decision
            except asyncio.CancelledError:
                canceled = self._updated(self._records[request.request_id], status="canceled")
                try:
                    self._commit(canceled)
                except Exception:
                    # Preserve cancellation even if persistence is unavailable.
                    # The disk record is orphaned; neither view may release work.
                    self._records[request.request_id] = self._updated(canceled, status="uncertain")
                raise
        finally:
            self._waiters.pop(request.request_id, None)
            future.cancel()

    def records(self, scope: ApprovalScope) -> tuple[ApprovalRecord, ...]:
        """Return detached snapshots visible within an adapter's authorized scope."""
        return tuple(
            copy.deepcopy(record) for record in self._records.values() if record.request.run_id in scope.run_ids
        )

    def pending(self, scope: ApprovalScope) -> tuple[ApprovalRecord, ...]:
        """Return outstanding requests for a reconnecting client."""
        return tuple(record for record in self.records(scope) if record.status == "pending")

    def resolve(self, decision: ApprovalDecision, *, scope: ApprovalScope, fingerprint: str) -> ApprovalResolution:
        """Resolve exactly one request without executing anything.

        Unknown and out-of-scope IDs both return ``unknown`` to avoid disclosing
        another caller's requests. Stale fingerprints, conflicting repeats, and
        expired/canceled/orphan requests never release an action.
        """
        key = decision.request_id
        record = self._records.get(key)
        status = "unknown"
        if record is not None and record.request.run_id in scope.run_ids:
            if fingerprint != record.fingerprint:
                status = "stale"
            elif record.status != "pending":
                status = "duplicate" if record.decision == decision else "already_resolved"
            elif key not in self._waiters or self._waiters[key].done():
                status = "already_resolved"
            elif record.expires_at is not None and time.time() >= record.expires_at:
                status = "expired"
                denial = ApprovalDecision(approved=False, request_id=key, reason="Approval expired")
                self._commit(self._updated(record, status="expired", decision=denial))
                self._waiters[key].set_result(denial)
            else:
                status = "approved" if decision.approved else "denied"
                self._commit(self._updated(record, status=status, decision=copy.deepcopy(decision)))
                self._waiters[key].set_result(copy.deepcopy(decision))
        return ApprovalResolution(key, status)

    async def events(self, scope: ApprovalScope) -> AsyncIterator[ApprovalRecord]:
        """Yield pending snapshots followed by resolutions for this adapter.

        Each subscriber gets its own stream. Close abandoned subscriptions; use
        ``pending`` to reconnect instead of relying on an unconsumed event queue.
        """
        queue: asyncio.Queue[ApprovalRecord] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            for record in self.pending(scope):
                yield record
            while True:
                record = await queue.get()
                if record.request.run_id in scope.run_ids:
                    yield record
        finally:
            self._subscribers.discard(queue)
