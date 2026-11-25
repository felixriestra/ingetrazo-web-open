"""Which edition is this: the open-source one, or a build that adds an SKP writer?

This repository is the open-source release and has no SKP writer (``formats/skp_out.py``),
so :func:`edition` says ``"open"``. The service reaches a writer only through
:func:`skp_export_module`, at run time, and every caller must cope with ``None``; nothing
may import it at module level. A build that adds one would also need
``INGETRAZO_WEB_ENABLE_SKP_EXPORT=1`` and the export lines commented out in
``interchange.py``. ``python -m web.backend edition`` prints what this package contains.

SKP **import** is open source (OpenSKP, MIT) and is always offered when ``openskp`` is
installed.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRIVATE_LIST = ROOT / "PRIVATE_FILES.txt"


def private_files() -> list[str]:
    """The paths listed as private (relative to the repository root), from an optional
    ``PRIVATE_FILES.txt``; this open-source release has none, so it is empty."""
    try:
        lines = PRIVATE_LIST.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def skp_export_present() -> bool:
    """Whether the SKP writer is part of this package."""
    try:
        return importlib.util.find_spec("formats.skp_out") is not None
    except (ImportError, ValueError):
        return False


def skp_export_enabled() -> bool:
    return skp_export_present() and os.environ.get("INGETRAZO_WEB_ENABLE_SKP_EXPORT") == "1"


def skp_export_module():
    """The SKP writer module, or ``None`` in the open-source edition (or when switched off)."""
    if not skp_export_enabled():
        return None
    try:
        return importlib.import_module("formats.skp_out")
    except ImportError:
        return None


def skp_import_available() -> bool:
    """Whether a SKP reader is installed (OpenSKP)."""
    try:
        from formats import skp as skp_format
    except ImportError:
        return False
    return any(available for _name, available in skp_format.backends_status())


def edition() -> str:
    return "private" if skp_export_present() else "open"


def describe() -> dict:
    present = [path for path in private_files() if (ROOT / path).exists()]
    return {
        "edition": edition(),
        "skp_import": {"available": skp_import_available(), "license": "open source (OpenSKP, MIT)"},
        "skp_export": {"present": skp_export_present(), "enabled": skp_export_enabled()},
        "private_files_listed": private_files(),
        "private_files_present": present,
    }
