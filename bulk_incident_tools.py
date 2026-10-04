"""Bulk maintenance of IBM QRadar SOAR incidents selected by creation time.

Typical use: cleaning up after a misbehaving rule or a test run that created
hundreds of incidents. Changes are only applied with ``--confirm``; without it
the tool prints what it would touch.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

LOG = logging.getLogger("bulk_incident_tools")
PAGE_SIZE = 500


def parse_iso8601(value: str) -> int:
    """ISO 8601 timestamp to epoch milliseconds; naive values are treated as UTC."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def build_query(
    start_ms: int, end_ms: int, start: int = 0, length: int = PAGE_SIZE
) -> dict[str, Any]:
    return {
        "filters": [
            {
                "conditions": [
                    {"field_name": "create_date", "method": "gte", "value": start_ms},
                    {"field_name": "create_date", "method": "lte", "value": end_ms},
                ]
            }
        ],
        "sorts": [{"field_name": "create_date", "type": "asc"}],
        "start": start,
        "length": length,
    }


def find_incidents(client: Any, start_ms: int, end_ms: int, limit: int) -> list[dict[str, Any]]:
    """Incidents created in the window (oldest first), at most ``limit``."""
    found: list[dict[str, Any]] = []
    while len(found) < limit:
        length = min(PAGE_SIZE, limit - len(found))
        page = client.post(
            "/incidents/query_paged?return_level=partial",
            build_query(start_ms, end_ms, len(found), length),
        )
        data = page.get("data") or []
        found.extend(data)
        if len(data) < length:
            break
    return found


def resolution_changes(summary: str, resolution: str, close: bool) -> dict[str, Any]:
    """Field values for closing; ``resolution`` may be a resolution label or its numeric ID."""
    changes: dict[str, Any] = {
        "resolution_id": int(resolution) if resolution.isdigit() else resolution,
        "resolution_summary": summary,
    }
    if close:
        changes["plan_status"] = "C"
    return changes


def update_incidents(
    client: Any, incident_ids: Sequence[int], changes: dict[str, Any]
) -> list[int]:
    import resilient

    failed = []
    for incident_id in incident_ids:
        try:
            patch = resilient.Patch(client.get(f"/incidents/{incident_id}"))
            for field, value in changes.items():
                patch.add_value(field, value)
            client.patch(f"/incidents/{incident_id}", patch, overwrite_conflict=True)
            LOG.info("Updated incident %s", incident_id)
        except Exception as exc:
            failed.append(incident_id)
            LOG.error("Could not update incident %s: %s", incident_id, exc)
    return failed


def delete_incidents(client: Any, incident_ids: Sequence[int]) -> list[int]:
    failed = []
    for incident_id in incident_ids:
        try:
            client.delete(f"/incidents/{incident_id}")
            LOG.info("Deleted incident %s", incident_id)
        except Exception as exc:
            failed.append(incident_id)
            LOG.error("Could not delete incident %s: %s", incident_id, exc)
    return failed


def get_client_from_env() -> Any:
    import resilient

    options: dict[str, Any] = {
        "host": os.environ.get("SOAR_HOST"),
        "port": int(os.environ.get("SOAR_PORT", "443")),
        "org": os.environ.get("SOAR_ORG"),
        "api_key_id": os.environ.get("SOAR_API_KEY_ID"),
        "api_key_secret": os.environ.get("SOAR_API_KEY_SECRET"),
    }
    missing = [key for key, value in options.items() if not value]
    if missing:
        raise SystemExit(f"Missing SOAR configuration: {', '.join(missing)}")
    if os.environ.get("SOAR_CAFILE"):
        options["cafile"] = os.environ["SOAR_CAFILE"]
    return resilient.get_client(options)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk list, close or delete IBM SOAR incidents by creation time."
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    list_cmd = commands.add_parser("list", help="list incidents created in the window")
    close_cmd = commands.add_parser("close", help="set a resolution and close the incidents")
    delete_cmd = commands.add_parser("delete", help="delete the incidents")
    for command in (list_cmd, close_cmd, delete_cmd):
        command.add_argument(
            "--start", required=True, help="window start, ISO 8601 (e.g. 2026-01-01T00:00:00Z)"
        )
        command.add_argument("--end", required=True, help="window end, ISO 8601")
        command.add_argument(
            "--limit",
            type=int,
            default=100,
            help="maximum number of incidents to touch (default 100)",
        )
    for command in (close_cmd, delete_cmd):
        command.add_argument(
            "--confirm",
            action="store_true",
            help="apply the change; without it only the plan is printed",
        )

    close_cmd.add_argument(
        "--resolution", required=True, help="resolution label (e.g. 'Not an Issue') or numeric ID"
    )
    close_cmd.add_argument("--summary", default="Closed during SOAR review")
    close_cmd.add_argument(
        "--leave-open", action="store_true", help="only set the resolution fields"
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    start_ms, end_ms = parse_iso8601(args.start), parse_iso8601(args.end)
    if end_ms <= start_ms:
        raise SystemExit("--end must be after --start")

    client = get_client_from_env()
    incidents = find_incidents(client, start_ms, end_ms, args.limit)
    ids = [incident["id"] for incident in incidents]
    applying = getattr(args, "confirm", False)
    print(
        json.dumps(
            {
                "command": args.command,
                "count": len(ids),
                "incident_ids": ids,
                "dry_run": not applying,
            },
            indent=2,
        )
    )

    if args.command == "list" or not ids:
        return 0
    if not applying:
        LOG.info("Dry run: re-run with --confirm to %s %d incident(s)", args.command, len(ids))
        return 0

    if args.command == "delete":
        failed = delete_incidents(client, ids)
    else:
        failed = update_incidents(
            client, ids, resolution_changes(args.summary, args.resolution, not args.leave_open)
        )
    LOG.info("%s: %d succeeded, %d failed", args.command, len(ids) - len(failed), len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
