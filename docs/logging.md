# Logging

Protolink provides a unified logging package to manage both console and file-based logs consistently.

## Overview

Protolink's logging is built around a common `BaseLogger` abstract class, which ensures that custom and built-in loggers expose the standard logging methods. 

<div align="center" style="font-family: 'Courier New', monospace; color:#888; font-size:14px; margin-bottom:12px;">
  [ ConsoleLogger ]   [ FileLogger ]   [ BaseLogger ]
</div>

By default, an Agent utilizes the `ConsoleLogger` to output colorful text to `stdout`, but it's very easy to substitute this with the `FileLogger` or even a custom subclass if you use platforms like Datadog or Sentry.

## Configuration

You can pass a logger instance directly when initializing your `Agent`. If you do not pass one, a `ConsoleLogger` is instantiated automatically, mapped to the selected `verbosity`.

```python
from protolink.agents import Agent
from protolink.logging import ConsoleLogger, FileLogger

# Using the built-in FileLogger (e.g., as JSON)
my_logger = FileLogger("agent_activity.log", extension="json", level="DEBUG")

# Pass it directly to your Agent
agent = Agent(
    card={
        "name": "logger_agent",
        "description": "Agent with file logging",
        "url": "http://127.0.0.1:8000",
    },
    transport="http",
    logger=my_logger,
)
```

!!! tip "Default Fallback"
    If you don't supply a `logger`, Protolink instantiates a `ConsoleLogger` for you automatically. The log level is derived from the `verbosity` argument passed to the Agent (`0` -> WARNING, `1` -> INFO, `2` -> DEBUG).

---

## Logging API Reference

All Protolink loggers must implement the `BaseLogger` interface.

### BaseLogger

The abstract base class ensuring compatibility across all loggers inside Protolink.

#### Core Methods

| Name | Parameters | Returns | Description |
|------|------------|---------|-------------|
| `debug()` | `message: str, **kwargs: Any` | `None` | Log a debug level message. |
| `info()` | `message: str, **kwargs: Any` | `None` | Log an info level message. |
| `warning()` | `message: str, **kwargs: Any` | `None` | Log a warning level message. |
| `error()` | `message: str, **kwargs: Any` | `None` | Log an error level message. |
| `exception()` | `message: str, **kwargs: Any` | `None` | Log an exception level message, capturing stack traces. |

### ConsoleLogger

Writes colored, formatted logs to standard output. 

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `name` | `str` | `"protolink"` | The name of the logger instance. |
| `level` | `int ⎪ str` | `logging.INFO` | The severity level. Can be a string like `"DEBUG"` or an integer. |
| `fmt` | `str` | `...` | The format string for the log message. |
| `datefmt` | `str` | `"%Y-%m-%d %H:%M:%S"` | The format string for the timestamp. |

### FileLogger

Appends formatted logs to a given file. Can automatically output structured JSON logs.

#### Constructor

| Parameter | Type | Default | Description |
|-----------|-----|---------|-------------|
| `filepath` | `str ⎪ Path` | — | **Required.** The target file to write logs to. Directories will be created if they do not exist. |
| `name` | `str` | `"protolink"` | The name of the logger instance. |
| `level` | `int ⎪ str` | `logging.INFO` | The severity level. Can be a string like `"DEBUG"` or an integer. |
| `extension` | `str ⎪ None` | `None` | Overrides the file extension. Passing `"json"` formats the output as structured JSON rows. |

!!! success "Structured JSON Logging"
    If the file you provide ends in `.json`, or if you pass `extension="json"` explicitly, the `FileLogger` automatically swaps out standard text formatting for structural JSON. This makes it extremely easy to ingest logs into tools like Elasticsearch or CloudWatch.
