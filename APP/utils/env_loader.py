"""Utilities for loading environment variables with graceful fallbacks.

This module provides a ``load_dotenv`` function that mirrors the behaviour of
``python-dotenv`` when the dependency is available while still allowing the
application to run in environments where the package cannot be installed.  The
codebase relies on ``load_dotenv`` in multiple modules (configuration loading
and UI helpers).  Import errors during start-up previously prevented the
application from running at all when ``python-dotenv`` was missing.  By
centralising the logic here we can attempt to import the third-party package
and transparently fall back to a lightweight parser implemented below.

The fallback intentionally supports the subset of ``.env`` syntax used by the
project (``KEY=VALUE`` pairs, optional ``export`` prefixes, simple quoting and
``#`` comments).  This keeps behaviour consistent across the whole project while
avoiding an external dependency in restricted environments such as the
evaluation sandbox.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised implicitly when dependency is available
    from dotenv import load_dotenv as _third_party_load_dotenv  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - runtime fallback
    def _normalize_lines(lines: Iterable[str]) -> Iterable[str]:
        """Yield cleaned lines from a .env file.

        The helper removes inline comments that start with ``#`` (only when they
        are not part of a quoted value) and strips surrounding whitespace.
        """

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "#" in line and not _is_quoted_value(line):
                line = line.split("#", 1)[0].strip()

            if line.startswith("export "):
                line = line[len("export ") :].lstrip()

            if line:
                yield line

    def _is_quoted_value(line: str) -> bool:
        """Return True when the assignment value is wrapped in quotes."""

        if "=" not in line:
            return False
        key, value = line.split("=", 1)
        value = value.strip()
        return bool(value) and value[0] == value[-1] and value[0] in {'"', "'"}

    def _parse_value(value: str) -> str:
        value = value.strip().strip('"').strip("'")
        return value.replace("\\n", "\n").replace("\\t", "\t")

    def _load_dotenv(
        dotenv_path: str | os.PathLike[str] | None = None,
        override: bool = False,
        **_: object,
    ) -> bool:
        """Simple .env loader used when python-dotenv is unavailable."""

        path = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
        if path.is_dir():
            path = path / ".env"

        if not path.exists():
            logger.debug(".env file not found at %s", path)
            return False

        changed = False
        try:
            for line in _normalize_lines(path.read_text(encoding="utf-8").splitlines()):
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                if override or key not in os.environ:
                    os.environ[key] = _parse_value(value)
                    changed = True
        except OSError as exc:
            logger.error("Không thể đọc file .env tại %s: %s", path, exc)
            return False

        return changed

    logger.info(
        "python-dotenv không khả dụng, sử dụng bộ phân tích .env nội bộ tối giản."
    )
else:
    def _load_dotenv(*args, **kwargs):  # pragma: no cover - thin wrapper
        return _third_party_load_dotenv(*args, **kwargs)


def load_dotenv(*args, **kwargs):
    """Public wrapper that mirrors python-dotenv's API surface."""

    return _load_dotenv(*args, **kwargs)

