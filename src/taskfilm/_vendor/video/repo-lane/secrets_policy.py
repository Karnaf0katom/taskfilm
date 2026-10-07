"""Fail-closed secret handling for untrusted repository sandbox runs.

The repository plan and every durable receipt cross an evidence boundary: neither
may carry a credential that an editor, capture worker, or later controller could
replay. This module stays dependency-free so the remote sandbox image uses the
same checks as offline contract tests.
"""

from __future__ import annotations

import re
from typing import Any


GITHUB_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,}(?![A-Za-z0-9_])"
)
AWS_ACCESS_KEY_RE = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?![A-Za-z0-9_-])"
)
URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")
_CREDENTIAL_FLAG_RE = re.compile(
    r"^--?(?:api[-_]?key|access[-_]?token|auth[-_]?token|github[-_]?token|"
    r"password|secret(?:[-_]?key)?|token)(?:=|$)",
    re.IGNORECASE,
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"^(?:api[-_]?key|access[-_]?token|auth[-_]?token|github[-_]?token|"
    r"password|secret(?:[-_]?key)?|token)\s*=",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    """Redact credential-shaped text while retaining non-secret diagnostics."""
    redacted = URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}[REDACTED]@", text)
    redacted = AWS_ACCESS_KEY_RE.sub("[REDACTED]", redacted)
    redacted = GITHUB_TOKEN_RE.sub("[REDACTED]", redacted)
    return JWT_RE.sub("[REDACTED]", redacted)


def require_safe_text(text: str, label: str) -> None:
    """Reject a plan field that carries credential-shaped data before execution."""
    if redact_text(text) != text:
        raise ValueError(f"{label} must not contain credentials or tokens")


def require_safe_argv(argv: list[str], label: str) -> None:
    """Reject command-line credential transport; sandbox jobs receive no repo secrets."""
    for index, item in enumerate(argv):
        item_label = f"{label}[{index}]"
        require_safe_text(item, item_label)
        if _CREDENTIAL_FLAG_RE.match(item) or _CREDENTIAL_ASSIGNMENT_RE.match(item):
            raise ValueError(f"{item_label} must not pass credentials or tokens")


def redact_json_strings(value: Any) -> Any:
    """Return a JSON-compatible value with every string routed through redaction."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            redact_text(key) if isinstance(key, str) else key: redact_json_strings(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json_strings(item) for item in value]
    if isinstance(value, tuple):
        return [redact_json_strings(item) for item in value]
    return value
