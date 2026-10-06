"""Model routing and bounded fallback on the existing default inference loop."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, ClassVar

from protolink.llms.base import LLM
from protolink.llms.history import ConversationHistory
from protolink.llms.serialization import json_history_default


class RoutedLLM(LLM):
    """Choose a model per step and fall back only on eligible request failures.

    Models may be configured LLM objects or normal provider:model aliases. A
    synchronous selector receives a copied canonical history and returns a model
    key. The default uses the first configured key. Fallbacks are tried in the
    supplied order after bounded retries. Every attempt is charged through the
    inference loop's shared budget callback and exposed stream output prevents
    fallback. Authentication, validation, policy and cancellation failures never
    trigger fallback. This wrapper never executes or replays tools.

    Routing uses the standard JSON action prompt and portable observations rather
    than mixing provider-native tool-call IDs across models. It inherits LLM.infer,
    so normal durable checkpoints remain supported. The application reconstructs
    its models/selector explicitly; credentials and callbacks are not serialized.
    """

    model_type: ClassVar = "api"
    provider: ClassVar = "router"

    def __init__(
        self,
        models: Mapping[str, LLM | str],
        *,
        selector: Callable[[ConversationHistory], str] | None = None,
        fallbacks: Sequence[str] = (),
        retries_per_model: int = 0,
    ) -> None:
        from protolink.llms.factory import create_llm

        if not models or any(not isinstance(key, str) or not key.strip() for key in models):
            raise ValueError("Configure at least one model with nonblank keys")
        if isinstance(retries_per_model, bool) or not isinstance(retries_per_model, int) or retries_per_model < 0:
            raise ValueError("retries_per_model must be a nonnegative integer")
        self.models = {key: create_llm(value) if isinstance(value, str) else value for key, value in models.items()}
        if any(not isinstance(model, LLM) or isinstance(model, RoutedLLM) for model in self.models.values()):
            raise TypeError("Routing requires concrete LLM adapters; nested routers are not supported")
        if any(key not in self.models for key in fallbacks) or len(set(fallbacks)) != len(fallbacks):
            raise ValueError("Fallback keys must be unique configured model names")
        if selector is not None and not callable(selector):
            raise TypeError("selector must be callable")
        self.selector, self.fallbacks, self.retries_per_model = selector, tuple(fallbacks), retries_per_model
        default_key = next(iter(self.models))
        self._selected: ContextVar[str] = ContextVar(f"protolink_route_{id(self)}", default=default_key)
        super().__init__(model="router", model_params={"routing": self.describe()})

    def describe(self) -> dict[str, Any]:
        """Return the declared routing contract without clients, callbacks or secrets."""

        def contract(model: LLM) -> dict[str, Any]:
            settings = {
                "parameters": model.model_params,
                "reasoning": model._reasoning,
                "base_url": getattr(model, "base_url", None),
            }
            return {
                "provider": model.provider,
                "model": model.model,
                "configuration": hashlib.sha256(
                    json.dumps(settings, sort_keys=True, default=json_history_default).encode()
                ).hexdigest(),
            }

        return {
            "models": {key: contract(model) for key, model in self.models.items()},
            "fallbacks": list(self.fallbacks),
            "retries_per_model": self.retries_per_model,
            "selector_configured": self.selector is not None,
        }

    def __getstate__(self) -> dict[str, Any]:
        """Keep copying configured routers compatible with task-local route state."""
        state = super().__getstate__()
        state.pop("_selected", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Rebuild routing scope when restoring a copied adapter."""
        super().__setstate__(state)
        default_key = next(iter(self.models))
        self._selected = ContextVar(f"protolink_route_{id(self)}", default=default_key)

    def call(self, history: ConversationHistory) -> str:
        """Generate plain action text through the selected adapter, with copied history."""
        return self.models[self._selected.get()].call(history.copy())

    async def call_stream(self, history: ConversationHistory) -> AsyncIterator[str]:
        """Forward one selected stream; an exposed partial result is never restarted."""
        from protolink.core.execution import closing_stream

        async with closing_stream(self.models[self._selected.get()].call_stream(history.copy())) as stream:
            async for chunk in stream:
                yield chunk

    async def _call_with_retry(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Charge every candidate attempt and annotate the successful normalized action."""
        selected = self.selector(self.history.copy()) if self.selector is not None else next(iter(self.models))
        if selected not in self.models:
            raise ValueError(f"Selector returned an unknown model key: {selected}")
        keys = [selected, *(key for key in self.fallbacks if key != selected)]
        before = kwargs.pop("_before_attempt", None)
        retry_predicate = kwargs.get("_retry_predicate")
        attempts = 0

        async def charge(_attempt):
            nonlocal attempts
            attempts += 1
            if before is not None:
                await before(attempts)

        for index, key in enumerate(keys):
            token = self._selected.set(key)
            try:
                result = await super()._call_with_retry(
                    fn, *args, **{**kwargs, "max_retries": self.retries_per_model, "_before_attempt": charge}
                )
                return replace(
                    result,
                    metadata={
                        **result.metadata,
                        "routing": {
                            "key": key,
                            "provider": self.models[key].provider,
                            "model": self.models[key].model,
                            "attempts": attempts,
                        },
                    },
                )
            except Exception as exc:
                if (
                    not self._is_transient_error(exc)
                    or index == len(keys) - 1
                    or (retry_predicate is not None and not retry_predicate(exc))
                ):
                    raise
            finally:
                self._selected.reset(token)
        raise RuntimeError("No routing candidate produced a response")

    def validate_connection(self) -> bool:
        """Explicitly validate every configured adapter; construction makes no calls."""
        return all(model.validate_connection() for model in self.models.values())
