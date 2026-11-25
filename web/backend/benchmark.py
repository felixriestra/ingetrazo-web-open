"""Measure the headless load and semantic-preview path on native documents.

Run from the repository root:

    python -m web.backend.benchmark examples/arco-yanque.igz

The JSON output is deliberately stable enough to archive in CI artifacts or
compare between branches. It is not a synthetic renderer benchmark: it times
the same validation, native loading, semantic collection, and GLB generation
used by the web API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import tempfile
import time

from .ingetrazo_web.scene_service import inspect_igz, preview_igz


def benchmark_document(path: str | Path) -> dict:
    source = Path(path).resolve()
    started = time.perf_counter()
    summary = inspect_igz(source)
    inspect_seconds = time.perf_counter() - started

    with tempfile.TemporaryDirectory(prefix="ingetrazo-benchmark-") as directory:
        target = Path(directory) / "preview.glb"
        started = time.perf_counter()
        preview_igz(source, target)
        preview_seconds = time.perf_counter() - started
        preview_bytes = target.stat().st_size

    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS reports bytes; Linux and the other supported Unix runners report
    # KiB. Normalize before this enters archived benchmark artifacts.
    peak_rss_bytes = int(usage.ru_maxrss)
    if sys.platform != "darwin":
        peak_rss_bytes *= 1024
    return {
        "schema": "ingetrazo.web-benchmark.v1",
        "document": source.name,
        "source_bytes": source.stat().st_size,
        "preview_bytes": preview_bytes,
        "inspect_seconds": round(inspect_seconds, 6),
        "preview_seconds": round(preview_seconds, 6),
        "peak_rss_bytes": peak_rss_bytes,
        "faces": int(summary["unique_geometry"]["faces"]),
        "placements": int(summary["placements"]),
        "reference_images": int(summary["reference_images"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="+", type=Path)
    parser.add_argument(
        "--max-preview-seconds", type=float,
        help="Exit unsuccessfully if any preview exceeds this duration.",
    )
    parser.add_argument(
        "--max-preview-mib", type=float,
        help="Exit unsuccessfully if any generated preview exceeds this size.",
    )
    args = parser.parse_args()
    results = [benchmark_document(path) for path in args.documents]
    failures = []
    for result in results:
        if (args.max_preview_seconds is not None
                and result["preview_seconds"] > args.max_preview_seconds):
            failures.append(
                f"{result['document']}: {result['preview_seconds']:.3f}s exceeds "
                f"{args.max_preview_seconds:.3f}s"
            )
        preview_mib = result["preview_bytes"] / 1024 / 1024
        if args.max_preview_mib is not None and preview_mib > args.max_preview_mib:
            failures.append(
                f"{result['document']}: {preview_mib:.2f} MiB exceeds "
                f"{args.max_preview_mib:.2f} MiB"
            )
    print(json.dumps({"results": results, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
