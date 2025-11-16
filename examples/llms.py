import argparse
from typing import Any, TypeVar

from protolink.models import Message

T = TypeVar("T")


def safe_import(module: str, class_name: str) -> type[Any] | None:
    """Safely import a class, returning None if the module is not available."""
    try:
        module = __import__(f"protolink.llms.{module}", fromlist=[class_name])
        return getattr(module, class_name, None)
    except ImportError:
        return None


def test_openai_llm() -> None:
    """Test the OpenAI LLM implementation."""
    if openai_llm := safe_import("api", "OpenAILLM"):
        print("\n=== Testing OpenAI LLM ===")
        try:
            llm = openai_llm()
            messages = [Message(role="user", content="Hello, how are you?")]

            print("\nTesting non-streaming response:")
            response = llm.generate_response(messages)
            print(f"Response: {response.content}")

            print("\nTesting streaming response:")
            for chunk in llm.generate_stream_response(messages):
                print(chunk.content, end="", flush=True)
            print("\n")
        except Exception as e:
            print(f"Error testing OpenAI: {e}")
    else:
        print("OpenAI client not available. Install with: pip install openai")


def test_anthropic_llm() -> None:
    """Test the Anthropic LLM implementation."""
    if anthropic_llm := safe_import("api", "AnthropicLLM"):
        print("\n=== Testing Anthropic LLM ===")
        try:
            llm = anthropic_llm()
            messages = [Message(role="user", content="Hello, how are you?")]

            print("\nTesting non-streaming response:")
            response = llm.generate_response(messages)
            print(f"Response: {response.content}")

            print("\nTesting streaming response:")
            for chunk in llm.generate_stream_response(messages):
                print(chunk.content, end="", flush=True)
            print("\n")
        except Exception as e:
            print(f"Error testing Anthropic: {e}")
    else:
        print("Anthropic client not available. Install with: pip install anthropic")


def main():
    parser = argparse.ArgumentParser(description="Test LLM implementations")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--openai", action="store_true", help="Test only OpenAI")
    group.add_argument("--anthropic", action="store_true", help="Test only Anthropic")

    args = parser.parse_args()

    no_args = not any([args.openai, args.anthropic])

    if args.openai or no_args:
        test_openai_llm()
    if args.anthropic or no_args:
        test_anthropic_llm()


if __name__ == "__main__":
    main()
