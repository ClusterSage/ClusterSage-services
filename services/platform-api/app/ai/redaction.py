from __future__ import annotations

import re


REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([A-Za-z0-9._-]+)"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"), r"\1[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(password\s*[=:]\s*)([^\s,;]+)"), r"\1[REDACTED_PASSWORD]"),
    (re.compile(r"(?i)(secret\s*[=:]\s*)([^\s,;]+)"), r"\1[REDACTED_SECRET]"),
    (re.compile(r"(?i)(token\s*[=:]\s*)([^\s,;]+)"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(?i)(access[_-]?key\s*[=:]\s*)([^\s,;]+)"), r"\1[REDACTED_ACCESS_KEY]"),
    (re.compile(r"(?i)(AccountKey=)([^;]+)"), r"\1[REDACTED_ACCOUNT_KEY]"),
    (re.compile(r"(?i)(SharedAccessKey=)([^;]+)"), r"\1[REDACTED_SHARED_ACCESS_KEY]"),
    (re.compile(r"(?i)(EndpointSuffix=)([^;]+)"), r"\1[REDACTED_ENDPOINT_SUFFIX]"),
    (re.compile(r"-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b"), "[REDACTED_JWT]"),
]


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
