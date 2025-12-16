"""Lazy imports for LLM backends"""


def require_gemini():
    """Lazy import for Google Gemini API."""
    try:
        import google.generativeai as genai
        from google.generativeai.types import GenerateContentResponse, GenerationConfig
    except ImportError as exc:
        raise ImportError(
            "Gemini LLM backend requires the 'google-genai' library. "
            "Install it with: uv add google-genai or uv add protolink[llms]"
        ) from exc
    return genai, GenerateContentResponse, GenerationConfig


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
