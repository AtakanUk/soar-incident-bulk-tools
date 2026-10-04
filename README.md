# SOAR Incident Bulk Tools

[![CI](https://github.com/AtakanUk/soar-incident-bulk-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/AtakanUk/soar-incident-bulk-tools/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Command-line tool for bulk maintenance of IBM QRadar SOAR incidents selected by creation time: list them, close them with a resolution, or delete them.

The typical situation: a noisy SIEM rule, a misconfigured escalation or a load test floods SOAR with hundreds of incidents within an hour. Closing them one by one in the UI is not realistic, and deleting the wrong ones is not reversible, so the tool is built to be boring and safe.

## Safety

- Incidents are selected by an explicit time window (`--start` / `--end`) and capped by `--limit` (default 100).
- `close` and `delete` are dry runs unless `--confirm` is given: the matching incident IDs are printed and nothing changes.
- Each incident is processed independently. Failures are logged, the rest continue, and the exit code is `1` if anything failed.
- Updates use `resilient.Patch` with `overwrite_conflict`, so incidents changed by a playbook in the meantime are still updated consistently.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `SOAR_HOST` | Yes | SOAR hostname |
| `SOAR_PORT` | No | API port (default `443`) |
| `SOAR_ORG` | Yes | Organization name |
| `SOAR_API_KEY_ID`, `SOAR_API_KEY_SECRET` | Yes | API key (needs incident read/edit, and delete for `delete`) |
| `SOAR_CAFILE` | No | CA bundle path, or `false` for self-signed lab instances |

## Usage

```bash
pip install -r requirements.txt

# what was created between 10:00 and 11:00 UTC?
python bulk_incident_tools.py list --start 2026-01-15T10:00:00Z --end 2026-01-15T11:00:00Z --limit 500

# plan, then apply
python bulk_incident_tools.py close --start 2026-01-15T10:00:00Z --end 2026-01-15T11:00:00Z \
    --limit 500 --resolution "Not an Issue" --summary "Duplicate alerts caused by rule misconfiguration"
python bulk_incident_tools.py close ... --confirm

# delete test incidents
python bulk_incident_tools.py delete --start 2026-01-15T10:00:00Z --end 2026-01-15T10:15:00Z --limit 50 --confirm
```

`--resolution` accepts the resolution label as configured in SOAR or its numeric ID. `--leave-open` sets the resolution fields without closing the incidents.

## Tests

```bash
pip install pytest
pytest
```

## License

[MIT](LICENSE)
