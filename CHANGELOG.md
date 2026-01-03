# Changelog

## 0.2.0
- Unraid-hardening: PUID/PGID support, /api/system, healthcheck, template + icon placeholders.
- Scanning correctness: stable planner, leaf-only defaults, foldercopy + sidecar options, LANraragi flatten + cbz naming, explicit skip reasons.
- Observability: diff endpoint/UI, last run cache, rotating file logs, enriched activity payloads.
- QA: added `scripts/self_test.py` nested-gallery harness.
- Automation: added auto-scan watcher + interval (default 30m) to trigger scans when sources change or on schedule.
