"""Lazy imports for LLM backends"""


def require_anthropic():
    """Lazy import for Anthropic API."""
    try:
        import anthropic
        from anthropic.types.message_stream_event import MessageStreamEvent
    except ImportError as exc:
        raise ImportError(
            "Anthropic LLM backend requires the 'anthropic' library. Install it with: uv add anthropic or uv add protolink[llms]"  # noqa: E501
        ) from exc
    return anthropic, MessageStreamEvent


def require_gemini():
    """Lazy import for Google Gemini API."""
    try:
        import google.genai as genai
        from google.genai.types import GenerateContentConfig
    except ImportError as exc:
        raise ImportError(
            "Gemini LLM backend requires the 'google-genai' library. "
            "Install it with: uv add google-genai or uv add protolink[llms]"
        ) from exc
    return genai, GenerateContentConfig


def require_hugging_face():
    """Lazy import for HuggingFace Inference API."""
    try:
        from huggingface_hub import InferenceClient
    except ImportError as exc:
        raise ImportError(
            "HuggingFace LLM backend requires the 'huggingface-hub' library. Install it with: uv add huggingface-hub or uv add protolink[llms]"  # noqa: E501
        ) from exc
    return InferenceClient


def require_openai():
    """Lazy import for OpenAI API."""
    try:
        import openai
        from openai.types.chat import ChatCompletion, ChatCompletionChunk
    except ImportError as exc:
        raise ImportError(
            "OpenAI LLM backend requires the 'openai' library. Install it with: uv add openai or uv add protolink[llms]"
        ) from exc
    return openai, ChatCompletion, ChatCompletionChunk


def require_ollama():
    """Lazy import for Ollama API."""
    try:
        from ollama import Client
    except ImportError as exc:
        raise ImportError(
            "Ollama LLM backend requires the 'ollama' library. Install it with: uv add ollama or uv add protolink[llms]"
        ) from exc
    return Client
