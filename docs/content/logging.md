import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Logging

Protolink provides a unified logging package to manage console, file-based, and intentionally silent logs consistently.

## Overview

Protolink's logging is built around a common `BaseLogger` abstract class, which ensures that custom and built-in loggers expose the standard logging methods. 

<div className="provider-strip-label">[ ConsoleLogger ]   [ FileLogger ]   [ QuietLogger ]   [ BaseLogger ]</div>

By default, an Agent utilizes the `ConsoleLogger` to output colorful text to `stdout`, but it's very easy to substitute this with the `FileLogger`, `QuietLogger`, or a custom subclass if you use platforms like Datadog or Sentry.

## Configuration

You can pass a logger instance directly when initializing your `Agent`. If you do not pass one, a `ConsoleLogger` is instantiated automatically, mapped to the selected `verbosity`.

```python
from protolink.agents import Agent
from protolink.logging import ConsoleLogger, FileLogger, QuietLogger

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

:::tip[Default Fallback]

If you don't supply a `logger`, Protolink instantiates a `ConsoleLogger` for you automatically. The log level is derived from the `verbosity` argument passed to the Agent (`0` suppresses the standard Agent logger methods, `1` -> INFO, `2` -> DEBUG).

:::
Use `QuietLogger` when you want a logger object but no emitted output at all:

```python
from protolink.agents import Agent
from protolink.logging import QuietLogger

agent = Agent(
    card={
        "name": "quiet_agent",
        "description": "Agent with no log output",
        "url": "http://127.0.0.1:8000",
    },
    transport="http",
    logger=QuietLogger(name="quiet_agent"),
)
```

:::note[Quiet vs. low verbosity]

`verbosity=0` keeps the default console logger but suppresses Protolink's standard Agent log calls. `QuietLogger` is a reusable no-op `BaseLogger` that creates no handlers and drops every `debug()`, `info()`, `warning()`, `error()`, and `exception()` call wherever it is injected.

:::
---

## Logging API Reference

All Protolink loggers must implement the `BaseLogger` interface.

<ApiSurface
  eyebrow="Logging module"
  title="Logger Interfaces"
  path="protolink.logging"
  description="The injectable logging surface for colorful console output, file-based logs, structured JSON rows, and intentionally silent production or test runs."
  pills={[
    "BaseLogger contract",
    "ConsoleLogger",
    "FileLogger",
    "QuietLogger",
    "Verbosity-aware agents",
  ]}
  cards={[
    {
      title: "Common methods",
      text: "Every logger exposes debug, info, warning, error, and exception methods.",
      code: "BaseLogger",
    },
    {
      title: "Console",
      text: "Human-readable local output for development, CLIs, and examples.",
      code: "ConsoleLogger",
    },
    {
      title: "Files",
      text: "Append text or structured JSON logs to a configured file path.",
      code: "FileLogger",
    },
    {
      title: "Silence",
      text: "Drop output while still satisfying the logger interface.",
      code: "QuietLogger",
    },
  ]}
/>

## Logger contract

### BaseLogger

<ApiReference
  kind="abstract class"
  path="protolink.logging.BaseLogger"
  signature={`class BaseLogger`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L7"
>

Define the minimal logging interface accepted by `Agent` and other ProtoLink
components. The class deliberately mirrors the familiar Python logging levels,
which makes custom adapters for structured logging or observability systems
small and predictable.

<ApiSection title="Abstract members">
  <ApiFields ariaLabel="BaseLogger abstract members">
    <ApiField name="name" type="str">
      Read-only logical logger name.
    </ApiField>
    <ApiField name="debug" type="(message: str, **kwargs: Any) -> None">
      Emit diagnostic detail.
    </ApiField>
    <ApiField name="info" type="(message: str, **kwargs: Any) -> None">
      Emit normal lifecycle or progress information.
    </ApiField>
    <ApiField name="warning" type="(message: str, **kwargs: Any) -> None">
      Emit a recoverable problem or caution.
    </ApiField>
    <ApiField name="error" type="(message: str, **kwargs: Any) -> None">
      Emit a failed operation.
    </ApiField>
    <ApiField name="exception" type="(message: str, **kwargs: Any) -> None">
      Emit a failure with exception context.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Custom implementations">
  Subclasses must implement the property and all five methods before they can be
  instantiated. ProtoLink does not require a subclass to wrap Python's standard
  <code>logging.Logger</code>.
</ApiCallout>

</ApiReference>

### BaseLogger.name

<ApiReference
  kind="abstract property"
  path="protolink.logging.BaseLogger.name"
  signature={`name -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L17"
>

Return the logical name associated with this logger. Built-in loggers retain the
constructor value unchanged.

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.name return value">
    <ApiField name="name" type="str">
      Logger identifier used for display and standard logging record names.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### BaseLogger.debug

<ApiReference
  kind="abstract method"
  path="protolink.logging.BaseLogger.debug"
  signature={`debug(
    message: str,
    **kwargs: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L22"
>

Record fine-grained diagnostic information that is normally hidden at the
default `INFO` threshold.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="BaseLogger.debug parameters">
    <ApiField name="message" type="str" required>
      Human-readable log message.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Implementation-defined context. The built-in console and file loggers use
      only <code>extra</code> for this level; other keys are ignored.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.debug return value">
    <ApiField name="None" type="None">
      Logging is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### BaseLogger.info

<ApiReference
  kind="abstract method"
  path="protolink.logging.BaseLogger.info"
  signature={`info(
    message: str,
    **kwargs: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L32"
>

Record ordinary lifecycle, status, or progress information.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="BaseLogger.info parameters">
    <ApiField name="message" type="str" required>
      Human-readable log message.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Implementation-defined context. Built-in emitting loggers forward
      <code>extra</code> to the standard logging record.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.info return value">
    <ApiField name="None" type="None">
      Logging is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### BaseLogger.warning

<ApiReference
  kind="abstract method"
  path="protolink.logging.BaseLogger.warning"
  signature={`warning(
    message: str,
    **kwargs: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L42"
>

Record a potentially harmful or unexpected condition that did not necessarily
stop the current operation.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="BaseLogger.warning parameters">
    <ApiField name="message" type="str" required>
      Human-readable warning.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Implementation-defined context. Built-in emitting loggers recognize
      <code>extra</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.warning return value">
    <ApiField name="None" type="None">
      Logging is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### BaseLogger.error

<ApiReference
  kind="abstract method"
  path="protolink.logging.BaseLogger.error"
  signature={`error(
    message: str,
    **kwargs: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L52"
>

Record a failed operation. Use `exception()` inside an active exception handler
when a traceback should be attached automatically.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="BaseLogger.error parameters">
    <ApiField name="message" type="str" required>
      Human-readable failure description.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Implementation-defined context. Built-in emitting loggers recognize
      <code>extra</code> and <code>exc_info</code>; omitted
      <code>exc_info</code> defaults to <code>False</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.error return value">
    <ApiField name="None" type="None">
      Logging is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### BaseLogger.exception

<ApiReference
  kind="abstract method"
  path="protolink.logging.BaseLogger.exception"
  signature={`exception(
    message: str,
    **kwargs: Any,
) -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/base.py#L62"
>

Record an error and, by default in the emitting built-ins, attach the active
exception traceback.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="BaseLogger.exception parameters">
    <ApiField name="message" type="str" required>
      Human-readable failure description.
    </ApiField>
    <ApiField name="**kwargs" type="Any">
      Implementation-defined context. Built-in console and file loggers
      recognize <code>extra</code> and <code>exc_info</code>; omitted
      <code>exc_info</code> defaults to <code>True</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="BaseLogger.exception return value">
    <ApiField name="None" type="None">
      Logging is performed for its side effect.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Built-in loggers

### ConsoleLogger

<ApiReference
  kind="class"
  path="protolink.logging.ConsoleLogger"
  signature={`class ConsoleLogger(
    name: str = "protolink",
    level: int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = logging.INFO,
    fmt: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/console.py#L30"
>

Write formatted, ANSI-colored records to `sys.stdout`. Each instance wraps a
standard logger named `console.&lt;name&gt;`, disables propagation to the root
logger, and replaces existing handlers on that standard logger to prevent
duplicate output after reconfiguration.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="ConsoleLogger constructor parameters">
    <ApiField name="name" type="str" defaultValue={'"protolink"'}>
      Logical name returned by the property and included in the underlying
      logger's record name.
    </ApiField>
    <ApiField name="level" type="int | log-level string" defaultValue="logging.INFO">
      Minimum emitted severity. Recognized strings are <code>DEBUG</code>,
      <code>INFO</code>, <code>WARNING</code>, <code>ERROR</code>, and
      <code>CRITICAL</code>. String matching is case-insensitive; an unknown
      string silently falls back to <code>INFO</code>.
    </ApiField>
    <ApiField name="fmt" type="str" defaultValue={'"%(asctime)s | %(levelname)s | %(name)s | %(message)s"'}>
      Standard-library logging format. Severity names are centered to eight
      characters by the console formatter before rendering.
    </ApiField>
    <ApiField name="datefmt" type="str" defaultValue={'"%Y-%m-%d %H:%M:%S"'}>
      Timestamp format passed to <code>logging.Formatter</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Behavior">
  <ApiFields ariaLabel="ConsoleLogger behavior">
    <ApiField name="debug / info / warning" type="method">
      Forward <code>message</code> and <code>kwargs["extra"]</code>; all other
      keyword arguments are ignored.
    </ApiField>
    <ApiField name="error / exception" type="method">
      Also forward <code>kwargs["exc_info"]</code>, defaulting to
      <code>False</code> for <code>error()</code> and <code>True</code> for
      <code>exception()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Shared standard logger">
  Constructing another <code>ConsoleLogger</code> with the same name clears and
  replaces that standard logger's handlers. Existing wrappers with that name
  therefore observe the new handler configuration.
</ApiCallout>

</ApiReference>

### FileLogger

<ApiReference
  kind="class"
  path="protolink.logging.FileLogger"
  signature={`class FileLogger(
    filepath: str | Path,
    name: str = "protolink",
    level: int | Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = logging.INFO,
    fmt: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    extension: str | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/file.py#L62"
>

Append UTF-8 log records to a file, creating missing parent directories. Output
is either conventional formatted text or one JSON object per log record.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="FileLogger constructor parameters">
    <ApiField name="filepath" type="str | Path" required>
      Destination file. It is opened in append mode and created when absent.
      Parent directories are created recursively.
    </ApiField>
    <ApiField name="name" type="str" defaultValue={'"protolink"'}>
      Logical logger name. The underlying standard logger also includes the
      destination path so different files do not share handlers.
    </ApiField>
    <ApiField name="level" type="int | log-level string" defaultValue="logging.INFO">
      Minimum emitted severity. Unknown strings silently resolve to
      <code>INFO</code>, matching <code>ConsoleLogger</code>.
    </ApiField>
    <ApiField name="fmt" type="str" defaultValue={'"%(asctime)s | %(levelname)s | %(name)s | %(message)s"'}>
      Standard logging format used only for non-JSON output.
    </ApiField>
    <ApiField name="datefmt" type="str" defaultValue={'"%Y-%m-%d %H:%M:%S"'}>
      Timestamp format used by both the text and JSON formatter.
    </ApiField>
    <ApiField name="extension" type="str | None" defaultValue="None">
      Format override. A case-insensitive <code>"json"</code> selects
      structured output; any other non-empty value selects text output.
      This option controls formatting only—it does not rename
      <code>filepath</code>. When omitted, the actual path suffix is used.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="JSON records">
  <ApiFields ariaLabel="FileLogger JSON record fields">
    <ApiField name="timestamp" type="str">
      Formatted record timestamp.
    </ApiField>
    <ApiField name="name" type="str">
      Underlying standard logger name.
    </ApiField>
    <ApiField name="level" type="str">
      Severity name.
    </ApiField>
    <ApiField name="message" type="str">
      Rendered record message.
    </ApiField>
    <ApiField name="extra" type="dict[str, Any]">
      Included when the record contains fields outside this formatter's
      standard-key list. On Python 3.12 and newer, the standard
      <code>taskName</code> field is not yet in that local exclusion list and
      can therefore appear here even without caller-provided context.
    </ApiField>
    <ApiField name="exc_info" type="str">
      Formatted traceback included only when exception information is attached.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="FileLogger constructor and logging errors">
    <ApiField name="OSError">
      File-system errors from directory creation or opening the destination
      propagate during construction.
    </ApiField>
    <ApiField name="KeyError">
      Python logging rejects <code>extra</code> keys that overwrite reserved
      <code>LogRecord</code> attributes.
    </ApiField>
    <ApiField name="formatter or write error">
      Errors raised inside the handler, including a non-JSON-serializable
      <code>extra</code> value, are passed to Python logging's
      <code>handleError()</code>. They are normally not re-raised to the logging
      caller, although development mode may print a diagnostic to stderr.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Structured output">
  A <code>.json</code> path or <code>extension="json"</code> produces
  newline-delimited JSON records, which can be ingested independently by log
  processors.
</ApiCallout>

</ApiReference>

### QuietLogger

<ApiReference
  kind="class"
  path="protolink.logging.QuietLogger"
  signature={`class QuietLogger(
    name: str = "protolink",
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/quiet.py#L8"
>

Satisfy the complete logger contract while intentionally discarding every
message. It creates no standard logger and no handlers, making it useful in
tests, embedded applications, or environments that route observability through
a different mechanism.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="QuietLogger constructor parameters">
    <ApiField name="name" type="str" defaultValue={'"protolink"'}>
      Logical value returned by the <code>name</code> property.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Behavior">
  <ApiFields ariaLabel="QuietLogger method behavior">
    <ApiField name="debug / info / warning / error / exception" type="method">
      Accept the same <code>message</code> and arbitrary keyword arguments as
      <code>BaseLogger</code>, ignore all values, and return
      <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

## Lifecycle message helpers

These small helpers are public because `Agent` uses them to produce friendly
startup and shutdown messages. Applications may use them as well, but their
exact wording is intentionally nondeterministic.

### get_agent_greeting

<ApiReference
  kind="function"
  path="protolink.logging.get_agent_greeting"
  signature={`get_agent_greeting(
    agent_name: str,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/config.py#L28"
>

Choose one startup phrase at random and interpolate the agent name with ANSI
bold styling.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="get_agent_greeting parameters">
    <ApiField name="agent_name" type="str" required>
      Name interpolated directly into the selected phrase.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="get_agent_greeting return value">
    <ApiField name="message" type="str">
      One of eight greeting strings, including emoji and ANSI escape sequences
      around the name.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Testing">
  The helper calls <code>random.choice()</code> on every invocation. Assert
  meaningful fragments rather than one exact sentence unless randomness is
  patched.
</ApiCallout>

</ApiReference>

### get_agent_farewell

<ApiReference
  kind="function"
  path="protolink.logging.get_agent_farewell"
  signature={`get_agent_farewell(
    agent_name: str,
) -> str`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/logging/config.py#L1"
>

Choose one shutdown phrase at random and interpolate the ANSI-bold agent name.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="get_agent_farewell parameters">
    <ApiField name="agent_name" type="str" required>
      Name interpolated directly into the selected phrase.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="get_agent_farewell return value">
    <ApiField name="message" type="str">
      One of eight farewell strings, including emoji and ANSI escape sequences
      around the name.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>
