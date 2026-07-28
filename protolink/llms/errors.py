"""Public exceptions raised by the controlled inference loop."""

from __future__ import annotations


class InferParseError(RuntimeError):
    """Report terminal action-parsing failure from :meth:`LLM.infer`.

    The infer loop normally returns malformed model output to the model for
    correction. This exception is raised only after the configured number of
    consecutive proposals have failed JSON decoding or action-schema
    validation.

    Args:
        attempts: Number of consecutive invalid action proposals. These are
            infer-loop correction attempts, not transient provider retries.
        step: Inference step at which the circuit breaker opened.
        raw_response: Exact final response returned by the LLM adapter.
            ``None`` means the adapter did not expose it; an empty string means
            the adapter returned an empty response.
        last_error: Parser or action-validation error from the final proposal.

    Attributes:
        explanation: Short description of the boundary the response failed to
            cross. The exact parser diagnostic remains available through
            ``last_error`` and the exception chain.

    Notes:
        ``raw_response`` is intentionally preserved without truncation so an
        application can export or inspect it. Treat it as potentially sensitive
        model output and avoid logging it blindly.
    """

    def __init__(
        self,
        *,
        attempts: int,
        step: int,
        raw_response: str | None,
        last_error: ValueError,
    ) -> None:
        self.attempts = attempts
        self.step = step
        self.raw_response = raw_response
        self.last_error = last_error
        self.explanation = self._explain_failure(raw_response, last_error)
        super().__init__(
            f"Failed to parse LLM output after {attempts} consecutive attempts.\n"
            f"Inference step: {step}\n"
            f"Explanation: {self.explanation}\n"
            f"Last error: {last_error}"
        )

    @staticmethod
    def _explain_failure(raw_response: str | None, last_error: ValueError) -> str:
        """Return a concise explanation without guessing at model intent."""
        if raw_response is None:
            return "The LLM adapter did not expose the raw response that failed validation."
        if raw_response == "":
            return "The LLM adapter returned an empty response, so no JSON action could be decoded."
        if not raw_response.strip():
            return "The LLM adapter returned only whitespace, so no JSON action could be decoded."
        if getattr(last_error, "parsed_data", None) is not None:
            return "The response decoded as JSON but did not match ProtoLink's action schema."
        return "The response could not be decoded as one valid ProtoLink JSON action."
