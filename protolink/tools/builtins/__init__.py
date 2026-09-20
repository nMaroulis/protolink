"""Opt-in tools and configurable integrations for common agent tasks.

Each factory returns a fresh :class:`protolink.tools.Tool`, so built-ins use the
same schema validation, AgentSkill advertising, capability policy, telemetry,
cancellation, and serialization paths as application-defined native tools.
Google/Microsoft backends optionally require HTTPX; imports and registration perform no
network or process execution. Configured backends/callbacks are not serialized.
"""

from collections.abc import Callable

from protolink.tools.tool import Tool

from ._google import GoogleAPIError, GoogleToken
from ._oauth import OAuthToken
from .calculator import calculator
from .calendar import CalendarBackend, GoogleCalendar, calendar_tools
from .clock import current_datetime
from .database import DatabaseBackend, SQLiteDatabase, database_tools
from .documents import document_tools
from .email import EmailBackend, Gmail, email_tools
from .filesystem import filesystem_tools
from .git import git_tool
from .http import HTTPHeaders, http_tool
from .imap_email import IMAPEmail, MailBackendError, MailPassword
from .outlook import MicrosoftGraphError, OutlookCalendar, OutlookEmail
from .process import process_tool
from .shell import shell_tool
from .storage import storage_tools
from .user_input import UserInputHandler, UserInputRequest, UserInputResult, ask_user_tool
from .web import fetch_url, web_search

_BUILTIN_FACTORIES: dict[str, Callable[[], Tool]] = {
    "calculator": calculator,
    "current_datetime": current_datetime,
    "fetch_url": fetch_url,
    "web_search": web_search,
}


def _create_builtin(builtin_id: str) -> Tool:
    """Restore one built-in through the fixed first-party factory registry."""
    factory = _BUILTIN_FACTORIES.get(builtin_id)
    if factory is None:
        raise ValueError(f"Unknown ProtoLink built-in tool: {builtin_id!r}")
    return factory()


__all__ = [
    "CalendarBackend",
    "DatabaseBackend",
    "EmailBackend",
    "Gmail",
    "GoogleAPIError",
    "GoogleCalendar",
    "GoogleToken",
    "HTTPHeaders",
    "IMAPEmail",
    "MailBackendError",
    "MailPassword",
    "MicrosoftGraphError",
    "OAuthToken",
    "OutlookCalendar",
    "OutlookEmail",
    "SQLiteDatabase",
    "UserInputHandler",
    "UserInputRequest",
    "UserInputResult",
    "ask_user_tool",
    "calculator",
    "calendar_tools",
    "current_datetime",
    "database_tools",
    "document_tools",
    "email_tools",
    "fetch_url",
    "filesystem_tools",
    "git_tool",
    "http_tool",
    "process_tool",
    "shell_tool",
    "storage_tools",
    "web_search",
]
