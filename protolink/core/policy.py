"""Capability policy and approval primitives for runtime actions.

The policy layer is deliberately independent of tools, language models,
transports, and user interfaces. It evaluates a prepared ``RunAction`` against
its ``RunContext`` and either authorizes the operation, denies it, or creates a
typed approval checkpoint for an application-provided handler.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from protolink.core.actions import RunAction
from protolink.core.redaction import RedactionPolicy
from protolink.core.run_context import RunContext
from protolink.utils import utc_now
from protolink.utils.id_generator import IDGenerator


class PolicyEffect(str, Enum):
    """Possible outcomes of evaluating one runtime action."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyDecision:
    """Serializable result returned by a runtime policy.

    Attributes:
        effect: Whether the action is allowed, denied, or requires approval.
        reason: Concise human-readable explanation of the decision.
        policy_name: Name of the policy implementation that made the decision.
        matched_capabilities: Required capabilities that determined the result.
        metadata: Additional policy-specific decision data.
    """

    effect: PolicyEffect
    reason: str
    policy_name: str
    matched_capabilities: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize public constructor values into the strict decision shape."""
        object.__setattr__(self, "effect", _coerce_effect(self.effect))
        object.__setattr__(self, "matched_capabilities", tuple(self.matched_capabilities))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision into a JSON-compatible dictionary."""
        return {
            "effect": self.effect.value,
            "reason": self.reason,
            "policy_name": self.policy_name,
            "matched_capabilities": list(self.matched_capabilities),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyDecision:
        """Create a policy decision from serialized data."""
        return cls(
            effect=_coerce_effect(data.get("effect", PolicyEffect.DENY)),
            reason=str(data.get("reason") or "Policy decision restored from serialized data"),
            policy_name=str(data.get("policy_name") or "policy"),
            matched_capabilities=tuple(str(item) for item in data.get("matched_capabilities") or []),
            metadata=dict(data.get("metadata") or {}),
        )


class Policy(Protocol):
    """Protocol implemented by asynchronous runtime action policies."""

    async def evaluate(self, action: RunAction, context: RunContext) -> PolicyDecision:
        """Evaluate an action in its run context without executing it."""
        ...


@dataclass(frozen=True)
class ApprovalRequest:
    """Typed checkpoint sent to an application approval handler.

    Attributes:
        action: Fully prepared operation awaiting approval.
        policy_decision: Decision that caused the checkpoint.
        run_id: Logical run correlated with the operation.
        request_id: Stable approval request identifier.
        created_at: ISO timestamp recording checkpoint creation.
        metadata: Extensible application metadata.
    """

    action: RunAction
    policy_decision: PolicyDecision
    run_id: str
    request_id: str = field(default_factory=lambda: IDGenerator.generate_context_id(prefix="approval_"))
    created_at: str = field(default_factory=lambda: utc_now())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redaction_policy: RedactionPolicy | None = None) -> dict[str, Any]:
        """Serialize the request into a JSON-compatible dictionary.

        Args:
            redaction_policy: Optional policy used to mask secrets before the
                dictionary is returned.
        """
        data = {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "action": self.action.to_dict(),
            "policy_decision": self.policy_decision.to_dict(),
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
        if redaction_policy is not None:
            return redaction_policy.redact(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        """Create an approval request from serialized data."""
        return cls(
            request_id=str(data.get("request_id") or IDGenerator.generate_context_id(prefix="approval_")),
            run_id=str(data.get("run_id") or ""),
            action=RunAction.from_dict(dict(data.get("action") or {})),
            policy_decision=PolicyDecision.from_dict(dict(data.get("policy_decision") or {})),
            created_at=str(data.get("created_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ApprovalDecision:
    """Application decision for one approval checkpoint.

    Attributes:
        approved: Whether the runtime may execute the requested action.
        request_id: Identifier of the corresponding ``ApprovalRequest``.
        reason: Optional explanation shown in traces or user interfaces.
        decided_by: Optional user, service, or policy actor identifier.
        metadata: Additional application decision data.
        decided_at: ISO timestamp recording the decision.
    """

    approved: bool
    request_id: str
    reason: str | None = None
    decided_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision into a JSON-compatible dictionary."""
        return {
            "approved": self.approved,
            "request_id": self.request_id,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "metadata": self.metadata,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalDecision:
        """Create an approval decision from serialized data."""
        return cls(
            approved=bool(data.get("approved", False)),
            request_id=str(data.get("request_id") or ""),
            reason=_optional_str(data.get("reason")),
            decided_by=_optional_str(data.get("decided_by")),
            metadata=dict(data.get("metadata") or {}),
            decided_at=str(data.get("decided_at") or utc_now()),
        )


class ApprovalHandler(Protocol):
    """Protocol for application-owned approval user experiences or services."""

    async def __call__(self, request: ApprovalRequest, context: RunContext) -> ApprovalDecision | bool:
        """Return an explicit decision for the supplied approval checkpoint."""
        ...


@dataclass(frozen=True)
class ActionAuthorization:
    """Successful authorization record returned before action execution.

    Attributes:
        action: Action approved for execution.
        policy_decision: Original policy result.
        approval_request: Approval checkpoint, when one was required.
        approval_decision: Application response to that checkpoint.
        authorized_at: ISO timestamp recording completed authorization.
    """

    action: RunAction
    policy_decision: PolicyDecision
    approval_request: ApprovalRequest | None = None
    approval_decision: ApprovalDecision | None = None
    authorized_at: str = field(default_factory=lambda: utc_now())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the authorization into a JSON-compatible dictionary."""
        return {
            "action": self.action.to_dict(),
            "policy_decision": self.policy_decision.to_dict(),
            "approval_request": self.approval_request.to_dict() if self.approval_request else None,
            "approval_decision": self.approval_decision.to_dict() if self.approval_decision else None,
            "authorized_at": self.authorized_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionAuthorization:
        """Create an authorization record from serialized data."""
        approval_request = data.get("approval_request")
        approval_decision = data.get("approval_decision")
        return cls(
            action=RunAction.from_dict(dict(data.get("action") or {})),
            policy_decision=PolicyDecision.from_dict(dict(data.get("policy_decision") or {})),
            approval_request=(
                ApprovalRequest.from_dict(approval_request) if isinstance(approval_request, dict) else None
            ),
            approval_decision=(
                ApprovalDecision.from_dict(approval_decision) if isinstance(approval_decision, dict) else None
            ),
            authorized_at=str(data.get("authorized_at") or utc_now()),
        )


class ActionPolicyError(RuntimeError):
    """Base exception for runtime policy failures carrying structured data."""

    def __init__(self, message: str, *, action: RunAction, decision: PolicyDecision) -> None:
        """Initialize a policy error with its action and decision records."""
        super().__init__(message)
        self.action = action
        self.decision = decision


class ApprovalRequiredError(ActionPolicyError):
    """Raised when an action needs approval but no handler is configured."""

    def __init__(self, request: ApprovalRequest) -> None:
        """Initialize the error from the unresolved approval request."""
        super().__init__(
            f"Action '{request.action.name}' requires approval",
            action=request.action,
            decision=request.policy_decision,
        )
        self.request = request


class ActionDeniedError(ActionPolicyError):
    """Raised when policy or an approval handler denies an action."""

    def __init__(
        self,
        *,
        action: RunAction,
        decision: PolicyDecision,
        approval_request: ApprovalRequest | None = None,
        approval_decision: ApprovalDecision | None = None,
    ) -> None:
        """Initialize a denial with optional approval records."""
        reason = approval_decision.reason if approval_decision and approval_decision.reason else decision.reason
        super().__init__(f"Action '{action.name}' denied: {reason}", action=action, decision=decision)
        self.approval_request = approval_request
        self.approval_decision = approval_decision


class CapabilityPolicy:
    """Evaluate actions using extensible capability rules.

    Rules map capability names to ``allow``, ``deny``, or
    ``require_approval``. Exact names and namespace wildcards such as
    ``"workspace.*"`` are supported. Runtime rules and compatible values from
    ``RunContext.permissions`` are combined using the most restrictive effect,
    so task metadata can narrow but cannot weaken runtime-owned policy.

    Permission values may be effects, booleans, or mappings. ``True`` means
    allow, ``False`` means deny, and a mapping without an explicit ``effect``
    is treated as a scoped grant. Applications needing path-, row-, account-,
    or resource-level checks should implement the ``Policy`` protocol and
    inspect the full action payload.
    """

    def __init__(
        self,
        rules: Mapping[str, PolicyEffect | str | bool | Mapping[str, Any]] | None = None,
        *,
        default_effect: PolicyEffect | str = PolicyEffect.ALLOW,
        name: str = "capability_policy",
    ) -> None:
        """Initialize a capability policy.

        Args:
            rules: Runtime-owned capability rules. Exact and ``.*`` wildcard
                keys are supported.
            default_effect: Result when neither runtime nor context rules match.
            name: Stable policy name included in decisions and traces.
        """
        self.rules = dict(rules or {})
        self.default_effect = _coerce_effect(default_effect)
        self.name = name

    def to_dict(self) -> dict[str, Any]:
        """Serialize this first-party policy as safe declarative configuration.

        Only JSON-compatible rule data is accepted. Policy implementations and
        approval callbacks are executable application objects and are therefore
        intentionally outside this format.

        Returns:
            A dictionary containing the stable policy type, rules, default
            effect, and name.

        Raises:
            TypeError: A capability name or nested rule value is not safe
                declarative data.
        """
        rules: dict[str, Any] = {}
        for capability, value in self.rules.items():
            if not isinstance(capability, str):
                raise TypeError("CapabilityPolicy rule names must be strings")
            if not isinstance(value, (PolicyEffect, str, bool, Mapping)):
                raise TypeError(f"CapabilityPolicy rule {capability!r} must be an effect, string, boolean, or mapping")
            _coerce_effect(value)
            rules[capability] = _policy_config_value(value)
        if not isinstance(self.name, str) or not self.name:
            raise TypeError("CapabilityPolicy name must be a non-empty string")
        return {
            "type": "capability",
            "rules": rules,
            "default_effect": self.default_effect.value,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CapabilityPolicy:
        """Restore first-party capability rules without importing executable code.

        Args:
            data: Declarative policy data produced by :meth:`to_dict`.

        Returns:
            A reconstructed :class:`CapabilityPolicy`.

        Raises:
            TypeError: The policy block contains a non-declarative value.
            ValueError: The policy type or top-level shape is invalid.
        """
        policy_type = data.get("type", "capability")
        if policy_type != "capability":
            raise ValueError(f"Unsupported serialized policy type: {policy_type!r}")
        raw_rules = data.get("rules", {})
        if not isinstance(raw_rules, Mapping):
            raise ValueError("Serialized CapabilityPolicy rules must be a mapping")

        rules: dict[str, Any] = {}
        for capability, value in raw_rules.items():
            if not isinstance(capability, str):
                raise TypeError("CapabilityPolicy rule names must be strings")
            if not isinstance(value, (str, bool, Mapping)):
                raise TypeError(
                    f"Serialized CapabilityPolicy rule {capability!r} must be a string, boolean, or mapping"
                )
            _coerce_effect(value)
            rules[capability] = _policy_config_value(value)

        name = data.get("name", "capability_policy")
        if not isinstance(name, str) or not name:
            raise ValueError("Serialized CapabilityPolicy name must be a non-empty string")
        return cls(
            rules,
            default_effect=data.get("default_effect", PolicyEffect.ALLOW.value),
            name=name,
        )

    async def evaluate(self, action: RunAction, context: RunContext) -> PolicyDecision:
        """Evaluate all capabilities required by an action.

        The strongest effect wins across capabilities: deny outranks approval,
        which outranks allow. A canceled run is always denied before capability
        rules are considered.
        """
        if context.canceled:
            return PolicyDecision(
                effect=PolicyEffect.DENY,
                reason=context.cancel_reason or "Run was canceled",
                policy_name=self.name,
                metadata={"canceled": True},
            )

        if not action.capabilities:
            return PolicyDecision(
                effect=PolicyEffect.ALLOW,
                reason="Action declares no protected capabilities",
                policy_name=self.name,
            )

        context_rules, context_default = _context_permission_rules(context.permissions)
        decisions: dict[str, PolicyEffect] = {}
        sources: dict[str, str] = {}

        for capability in sorted(action.capabilities):
            runtime_value = _match_rule(self.rules, capability)
            context_value = _match_rule(context_rules, capability)
            runtime_effect = _coerce_effect(runtime_value) if runtime_value is not None else self.default_effect
            context_effect = None
            context_source = None
            if context_value is not None:
                context_effect = _coerce_effect(context_value)
                context_source = "context"
            elif context_default is not None:
                context_effect = _coerce_effect(context_default)
                context_source = "context_default"

            effect = runtime_effect
            source = "policy" if runtime_value is not None else "policy_default"
            if context_effect is not None and _effect_rank(context_effect) > _effect_rank(effect):
                effect = context_effect
                source = context_source or "context"
            elif context_effect is not None and context_effect is effect:
                source = f"{source}+{context_source}"
            decisions[capability] = effect
            sources[capability] = source

        strongest = max(decisions.values(), key=_effect_rank)
        matched = tuple(capability for capability, effect in decisions.items() if effect is strongest)
        return PolicyDecision(
            effect=strongest,
            reason=_decision_reason(strongest, matched),
            policy_name=self.name,
            matched_capabilities=matched,
            metadata={
                "capabilities": {capability: effect.value for capability, effect in decisions.items()},
                "sources": sources,
            },
        )


ApprovalHandlerLike = (
    ApprovalHandler
    | Callable[[ApprovalRequest, RunContext], ApprovalDecision | bool | Awaitable[ApprovalDecision | bool]]
)
"""Accepted callable shape for synchronous or asynchronous approval handlers."""


def _policy_config_value(value: Any) -> Any:
    """Normalize nested policy configuration into JSON-compatible values."""
    if isinstance(value, PolicyEffect):
        return value.value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("CapabilityPolicy configuration numbers must be finite")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise TypeError("CapabilityPolicy configuration keys must be strings")
            normalized[key] = _policy_config_value(nested_value)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_policy_config_value(item) for item in value]
    raise TypeError(f"CapabilityPolicy configuration contains unsupported value {type(value).__name__}")


class ActionAuthorizer:
    """Coordinate policy evaluation and optional application approval.

    The authorizer is the only component that turns a policy decision into an
    execution authorization. It fails closed when approval is required and no
    handler is installed, and it preserves every decision as typed data for
    events, traces, tests, and user interfaces.
    """

    def __init__(
        self,
        policy: Policy | None = None,
        approval_handler: ApprovalHandlerLike | None = None,
    ) -> None:
        """Initialize the authorizer with a policy and optional handler."""
        self.policy = policy or CapabilityPolicy()
        self.approval_handler = approval_handler

    async def authorize(self, action: RunAction, context: RunContext) -> ActionAuthorization:
        """Authorize an action or raise a structured policy exception.

        Args:
            action: Fully prepared action awaiting execution.
            context: Run context supplying cancellation and permission state.

        Returns:
            A successful authorization record.

        Raises:
            ActionDeniedError: The policy or approver denied the action.
            ApprovalRequiredError: Approval is required but no handler exists.
        """
        decision = await self.policy.evaluate(action, context)
        if decision.effect is PolicyEffect.DENY:
            raise ActionDeniedError(action=action, decision=decision)
        if decision.effect is PolicyEffect.ALLOW:
            return ActionAuthorization(action=action, policy_decision=decision)

        request = ApprovalRequest(action=action, policy_decision=decision, run_id=context.run_id)
        if self.approval_handler is None:
            raise ApprovalRequiredError(request)

        handler_result = self.approval_handler(request, context)
        if inspect.isawaitable(handler_result):
            handler_result = await handler_result
        approval = _coerce_approval_decision(handler_result, request)
        if not approval.approved:
            raise ActionDeniedError(
                action=action,
                decision=decision,
                approval_request=request,
                approval_decision=approval,
            )

        return ActionAuthorization(
            action=action,
            policy_decision=decision,
            approval_request=request,
            approval_decision=approval,
        )


def _coerce_approval_decision(value: Any, request: ApprovalRequest) -> ApprovalDecision:
    """Normalize a handler result and validate request correlation."""
    if isinstance(value, bool):
        return ApprovalDecision(approved=value, request_id=request.request_id)
    if not isinstance(value, ApprovalDecision):
        raise TypeError("Approval handler must return ApprovalDecision or bool")
    if value.request_id != request.request_id:
        raise ValueError("Approval decision request_id does not match the approval request")
    return value


def _context_permission_rules(
    permissions: Mapping[str, Any],
) -> tuple[dict[str, Any], PolicyEffect | str | bool | Mapping[str, Any] | None]:
    """Extract capability rules and an optional default from run permissions."""
    nested = permissions.get("capabilities")
    rules = (
        dict(nested)
        if isinstance(nested, Mapping)
        else {key: value for key, value in permissions.items() if key not in {"default", "capabilities"}}
    )
    return rules, permissions.get("default")


def _match_rule(rules: Mapping[str, Any], capability: str) -> Any | None:
    """Return the most specific exact or namespace-wildcard rule."""
    if capability in rules:
        return rules[capability]

    matches: list[tuple[int, Any]] = []
    for pattern, value in rules.items():
        if pattern == "*":
            matches.append((0, value))
        elif pattern.endswith(".*") and capability.startswith(pattern[:-1]):
            matches.append((len(pattern), value))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _coerce_effect(value: Any) -> PolicyEffect:
    """Normalize public rule forms into a strict ``PolicyEffect``."""
    if isinstance(value, PolicyEffect):
        return value
    if isinstance(value, bool):
        return PolicyEffect.ALLOW if value else PolicyEffect.DENY
    if isinstance(value, Mapping):
        explicit = value.get("effect", value.get("decision", value.get("mode")))
        return PolicyEffect.ALLOW if explicit is None else _coerce_effect(explicit)

    normalized = str(value).strip().lower().replace("-", "_")
    aliases = {
        "allow": PolicyEffect.ALLOW,
        "allowed": PolicyEffect.ALLOW,
        "deny": PolicyEffect.DENY,
        "denied": PolicyEffect.DENY,
        "approval": PolicyEffect.REQUIRE_APPROVAL,
        "approve": PolicyEffect.REQUIRE_APPROVAL,
        "ask": PolicyEffect.REQUIRE_APPROVAL,
        "require_approval": PolicyEffect.REQUIRE_APPROVAL,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported policy effect: {value!r}") from exc


def _effect_rank(effect: PolicyEffect) -> int:
    """Return the restrictiveness rank used to combine capability decisions."""
    return {
        PolicyEffect.ALLOW: 0,
        PolicyEffect.REQUIRE_APPROVAL: 1,
        PolicyEffect.DENY: 2,
    }[effect]


def _decision_reason(effect: PolicyEffect, capabilities: tuple[str, ...]) -> str:
    """Build a concise explanation for a combined capability decision."""
    joined = ", ".join(capabilities)
    if effect is PolicyEffect.DENY:
        return f"Denied capabilities: {joined}"
    if effect is PolicyEffect.REQUIRE_APPROVAL:
        return f"Approval required for capabilities: {joined}"
    return f"Allowed capabilities: {joined}"


def _optional_str(value: Any) -> str | None:
    """Return ``value`` as a string while preserving ``None``."""
    if value is None:
        return None
    return str(value)
