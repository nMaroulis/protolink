"""Google OAuth adapter; credentials never enter tool data."""

from __future__ import annotations

from protolink.tools.builtins._oauth import OAuthJSONAPI, OAuthToken

GoogleToken = OAuthToken
"""An OAuth access token or application callback supplying a fresh token per request."""


class GoogleAPIError(RuntimeError):
    """Google rejected a request; response bodies and credentials are not echoed."""

    def __init__(self, status_code: int) -> None:
        """Retain the HTTP status for application-owned retry/authentication handling."""
        self.status_code = status_code
        super().__init__(f"Google API request failed (HTTP {status_code}); no automatic retry was attempted")


class GoogleAPI(OAuthJSONAPI):
    """Use fixed HTTPS endpoints, bounded responses, and no automatic retries."""

    def __init__(self, token: GoogleToken, base_url: str) -> None:
        super().__init__(token, base_url, provider="Google", error_type=GoogleAPIError)
