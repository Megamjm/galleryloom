# Changelog

## 0.2.2
- Fixed cross-device zip finalization: prefer temp files in the destination, EXDEV-safe copy+replace fallback, and cleanup of partial artifacts.
- Config: optional `TEMP_DIR` override plus `BROWSE_ROOTS` list for the new folder picker.
- API/UI: `/api/fs` browse endpoints and Sources page modal picker to select directories without pasting paths.
- QA: unit coverage for EXDEV fallback and browse path traversal guards; docs updated for JSON list env vars.

## 0.2.1
- Added auto-scan watcher + interval (default 30m) to trigger scans when sources change or on schedule.

## 0.2.0
- Unraid-hardening: PUID/PGID support, /api/system, healthcheck, template + icon placeholders.
- Scanning correctness: stable planner, leaf-only defaults, foldercopy + sidecar options, LANraragi flatten + cbz naming, explicit skip reasons.
- Observability: diff endpoint/UI, last run cache, rotating file logs, enriched activity payloads.
- QA: added `scripts/self_test.py` nested-gallery harness.
