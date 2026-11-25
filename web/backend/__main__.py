"""Run the web service: ``python -m web.backend``, and manage its users.

    python -m web.backend                       # serve (loopback unless accounts exist)
    python -m web.backend users add NAME [--admin]   # create a user; prints the access token once
    python -m web.backend users token NAME      # issue a new token (the old one stops working)
    python -m web.backend users list
    python -m web.backend users remove NAME
    python -m web.backend edition               # private or open-source package, and what is in it
    python -m web.backend prune [--keep N]      # delete old revisions now (default: INGETRAZO_WEB_KEEP_REVISIONS)

Binds to loopback only unless accounts are on (see ``ingetrazo_web/auth.py``): beyond this
machine the service needs users, and should sit behind TLS. Without accounts, exposing it
needs ``INGETRAZO_WEB_ALLOW_REMOTE=1`` and your own authenticating proxy.
"""
from __future__ import annotations

import ipaddress
import os
import sys

LOOPBACK_NAMES = {"localhost"}


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _data_root():
    from pathlib import Path
    from web.backend.ingetrazo_web.app import _DEFAULT_DATA
    return Path(os.environ.get("INGETRAZO_WEB_DATA", str(_DEFAULT_DATA)))


def users_command(arguments: list[str]) -> int:
    from web.backend.ingetrazo_web.auth import Users

    users = Users(_data_root())
    action = arguments[0] if arguments else "list"
    try:
        if action == "add" and len(arguments) >= 2:
            token = users.add(arguments[1], "admin" if "--admin" in arguments[2:] else "user")
            print(f"Created {arguments[1]}. Access token (shown once, keep it safe):\n{token}")
        elif action == "token" and len(arguments) == 2:
            token = users.add(arguments[1], rotate=True)
            print(f"New access token for {arguments[1]} (the old one no longer works):\n{token}")
        elif action == "remove" and len(arguments) == 2:
            print("Removed." if users.remove(arguments[1]) else "No such user.")
        elif action == "list":
            for item in users.names():
                print(f"{item['name']}\t{item['role']}")
        else:
            print(__doc__)
            return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def prune_command(arguments: list[str]) -> int:
    from web.backend.ingetrazo_web.document_store import DocumentStore

    keep = None
    if "--keep" in arguments:
        try:
            keep = int(arguments[arguments.index("--keep") + 1])
        except (IndexError, ValueError):
            print("--keep needs a number", file=sys.stderr)
            return 2
    store = DocumentStore(_data_root())
    limit = store.keep_revisions if keep is None else keep
    if not limit:
        print("No limit set: pass --keep N or set INGETRAZO_WEB_KEEP_REVISIONS.", file=sys.stderr)
        return 2
    total = 0
    for record in store.list():
        removed = store.prune(record["id"], limit)
        total += len(removed)
        if removed:
            print(f"{record['name']}: removed {len(removed)} old revisions")
    print(f"Removed {total} revisions.")
    return 0


def main() -> None:
    import uvicorn

    if len(sys.argv) > 1 and sys.argv[1] == "users":
        sys.exit(users_command(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "edition":
        from web.backend.ingetrazo_web.edition import describe
        info = describe()
        print(f"edition: {info['edition']}")
        print(f"SKP import: {'available' if info['skp_import']['available'] else 'not available (install openskp)'} ({info['skp_import']['license']})")
        print(f"SKP export: {'present' if info['skp_export']['present'] else 'not in this package'}"
              + (f", {'enabled' if info['skp_export']['enabled'] else 'off (INGETRAZO_WEB_ENABLE_SKP_EXPORT=1 turns it on)'}" if info['skp_export']['present'] else ""))
        print("private files listed:", ", ".join(info["private_files_listed"]) or "none")
        print("private files present:", ", ".join(info["private_files_present"]) or "none")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "prune":
        sys.exit(prune_command(sys.argv[2:]))
    host = os.environ.get("INGETRAZO_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("INGETRAZO_WEB_PORT", "8000"))
    if not _is_loopback(host):
        from web.backend.ingetrazo_web.auth import Users
        accounts = os.environ.get("INGETRAZO_WEB_AUTH") == "1" or Users(_data_root()).any()
        if os.environ.get("INGETRAZO_WEB_AUTH") in {"0", "off"}:
            accounts = False
        if accounts:
            if os.environ.get("INGETRAZO_WEB_SECURE_COOKIES") != "1":
                print("NOTE: serving accounts over plain HTTP; put TLS in front and set "
                      "INGETRAZO_WEB_SECURE_COOKIES=1.", file=sys.stderr)
        elif os.environ.get("INGETRAZO_WEB_ALLOW_REMOTE") != "1":
            sys.exit(
                f"Refusing to bind {host}: no user accounts exist. Create one with "
                "`python -m web.backend users add NAME --admin`, or set "
                "INGETRAZO_WEB_ALLOW_REMOTE=1 only behind your own authenticating proxy."
            )
        else:
            print(f"WARNING: serving unauthenticated on {host}:{port}", file=sys.stderr)
    uvicorn.run("web.backend.ingetrazo_web.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
