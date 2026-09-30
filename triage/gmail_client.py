from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
DRY_RUN_METHODS = frozenset(
    {
        "users.getProfile",
        "users.history.list",
        "users.labels.list",
        "users.messages.list",
        "users.messages.get",
    }
)
APPLY_METHODS = frozenset(
    {
        "users.getProfile",
        "users.labels.list",
        "users.labels.create",
        "users.messages.get",
        "users.messages.modify",
    }
)


class Gmail(Protocol):
    def call(self, method: str, **kwargs: Any) -> Mapping[str, Any]: ...


class MethodNotAllowed(ValueError):
    pass


class GmailClient:
    def __init__(self, service: Any, allowed_methods: frozenset[str]):
        self._service = service
        self.allowed_methods = allowed_methods

    def call(self, method: str, **kwargs: Any) -> Mapping[str, Any]:
        if method not in self.allowed_methods:
            raise MethodNotAllowed(f"Gmail method not allowed: {method}")
        users = self._service.users()
        if method == "users.getProfile":
            request = users.getProfile(**kwargs)
        elif method == "users.history.list":
            request = users.history().list(**kwargs)
        elif method == "users.labels.list":
            request = users.labels().list(**kwargs)
        elif method == "users.labels.create":
            request = users.labels().create(**kwargs)
        elif method == "users.messages.list":
            request = users.messages().list(**kwargs)
        elif method == "users.messages.get":
            request = users.messages().get(**kwargs)
        elif method == "users.messages.modify":
            request = users.messages().modify(**kwargs)
        else:
            raise MethodNotAllowed(f"Gmail method not allowed: {method}")
        return request.execute()


def _credentials(scope: str, client_secret_path: str, token_path: str) -> Credentials:
    token = Path(token_path)
    if token.exists():
        credentials = Credentials.from_authorized_user_file(token, [scope])
        if set(credentials.scopes or ()) == {scope} and credentials.has_scopes([scope]):
            return credentials
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, [scope])
    credentials = flow.run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(credentials.to_json())
    token.chmod(0o600)
    return credentials


def client_from_environment(mode: str) -> GmailClient:
    secret = os.environ.get("GOOGLE_CLIENT_SECRET_PATH")
    token = os.environ.get("GOOGLE_TOKEN_PATH")
    if not secret:
        raise ValueError("GOOGLE_CLIENT_SECRET_PATH is required")
    if not token:
        raise ValueError("GOOGLE_TOKEN_PATH is required")
    if mode == "dry_run":
        scope, methods = READONLY_SCOPE, DRY_RUN_METHODS
    elif mode == "apply":
        scope, methods = MODIFY_SCOPE, APPLY_METHODS
    else:
        raise ValueError("mode must be dry_run or apply")
    return GmailClient(
        build("gmail", "v1", credentials=_credentials(scope, secret, token), cache_discovery=False),
        methods,
    )
