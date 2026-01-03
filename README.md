# GalleryLoom (Zip Merge)

A minimal FastAPI + SQLite MVP that scans mounted media under `/data`, copies archives, and zips (or folder-copies) qualifying gallery folders into `/output` while logging activity to `/config/galleryloom.db`. Optional duplicates land in `/duplicates`. A simple web UI covers sources, settings, dry-run, run, diff, and activity.

## Features
- Sources: name + relative path under `/data`, enabled flag, scan modes (`both | archives_only | folders_only`); signatures stored for change detection.
- Planner: zip/foldercopy/zip+foldercopy output modes; leaf-only and/or recursive counting; nested replication or LANraragi flatten with collision-safe naming.
- Skip/decision reasons: `SKIP_NO_IMAGES`, `SKIP_BELOW_MIN_IMAGES`, `SKIP_DUPLICATE_SAME_SIGNATURE`, `SKIP_DUPLICATE_SAME_SIZE`, `SKIP_OUTPUT_CONFLICT`, `SKIP_EXISTING_UNCHANGED`.
- Duplicate handling: optional `/duplicates` sink or automatic rename with timestamp; signatures used to avoid rework; existing size/signature checks.
- Auto-scan: background watcher + interval (default 30 minutes) that enqueues scans on source changes or schedule; manual Dry Run/Run buttons remain.
- Diff & history: `/api/scan/diff` compares current sources vs DB; `/api/scan/last` returns last dry-run/run; activity table persisted in SQLite.
- Logging: stdout plus rotating file logs under `/config/logs`; optional debug log with per-action traces when enabled.
- SQLite in WAL mode at `/config/galleryloom.db`; activity, archive_records (with virtual paths), settings, sources stored.

## Run with Docker
```
docker build -t galleryloom .
docker run -p 8080:8080 \
  -v /path/to/data:/data:ro \
  -v /path/to/output:/output \
  -v /path/to/galleryloom/config:/config \
  -v /path/to/duplicates:/duplicates \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  galleryloom
```
Notes for Unraid: map `/data` (usually read-only), `/output` (rw), `/config` (rw, holds SQLite + tmp + logs), `/duplicates` (rw, optional). Container listens on `8080`. `PUID`/`PGID` (optional) chown created dirs under `/config` and `/output`.

## Docker Compose (dev sample)
`docker-compose up --build` mounts `./dev-data`, `./dev-output`, `./dev-config`, `./dev-duplicates` and serves at http://localhost:8080.

## Unraid Template
- A starter template lives at `unraid/template.xml` with the expected path mappings and optional `PUID`/`PGID`.
- `unraid/icon.png` is a placeholder; replace as desired.
- Recommended mappings:
  - `/data` → read-only library root
  - `/output` → writable normalized library
  - `/config` → writable appdata (DB + logs)
  - `/duplicates` → optional duplicate sink

## Install on Unraid (GUI)
1. In Unraid, go to *Docker* → *Add Container* → *Template repositories* and add your template repo or paste `https://raw.githubusercontent.com/<your-username>/galleryloom/main/unraid/template.xml`.
2. Choose the GalleryLoom template.
3. Set paths: `/data` (ro), `/output` (rw), `/config` (rw), `/duplicates` (rw, optional).
4. (Optional) Set `PUID`/`PGID` if you want created files owned by a specific user/group.
5. Deploy, then open the WebUI and configure Sources/Settings.

## Install on Unraid (CLI)
```
docker run -d --name=galleryloom \
  -p 8080:8080 \
  -v /mnt/user/yourdata:/data:ro \
  -v /mnt/user/galleryloom-output:/output \
  -v /mnt/user/appdata/galleryloom:/config \
  -v /mnt/user/galleryloom-duplicates:/duplicates \
  -e PUID=99 -e PGID=100 \
  ghcr.io/yourorg/galleryloom:latest
```
Replace volume paths and image tag with your registry. `/duplicates` is optional.

## Local dev
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
GLOOM_DATA_ROOT=./dev-data \
GLOOM_OUTPUT_ROOT=./dev-output \
GLOOM_CONFIG_ROOT=./dev-config \
GLOOM_DUPLICATES_ROOT=./dev-duplicates \
GLOOM_TMP_ROOT=./dev-config/tmp \
.venv/bin/uvicorn app.main:app --reload --port 8080
```
Visit the UI at `/`, `/sources`, `/settings`. API examples:
- `curl -X POST http://localhost:8080/api/scan/dryrun`
- `curl -X POST http://localhost:8080/api/scan/run`
- `curl http://localhost:8080/api/activity`
- `curl http://localhost:8080/api/system`
- `curl -X POST http://localhost:8080/api/scan/diff`

## LANraragi compatibility
- `lanraragi_flatten=true` places archives at the `/output` root while tracking their virtual nested paths in the DB (collisions append `__{hash}`).
- `archive_extension_for_galleries` can be set to `cbz` while still producing ZIP-format archives.

## Self-test (bundled dev data)
A tiny fake library is in `dev-data/`:
- `Manga/SeriesA/Chapter1/` with 3 `.jpg` files and an existing `Chapter1.zip` archive.
- `Manga/SeriesA/Chapter2/` with 3 `.png` files.
- `Manga/SeriesB/Extras/` with one `.jpeg` (below min-images threshold).
- `Archives/sample.cbz`.

Run the quick check (after installing deps as above):
```
GLOOM_DATA_ROOT=./dev-data GLOOM_OUTPUT_ROOT=./dev-output \
GLOOM_CONFIG_ROOT=./dev-config GLOOM_DUPLICATES_ROOT=./dev-duplicates \
GLOOM_TMP_ROOT=./dev-config/tmp \
.venv/bin/python - <<'PY'
import asyncio, json
from sqlalchemy import select
from app.core.db import init_db, SessionLocal
from app.core import models
from app.services.scan_service import perform_scan
from app.services.settings_service import get_settings
async def main():
    await init_db()
    async with SessionLocal() as s:
        await get_settings(s)
        if not (await s.execute(select(models.Source).where(models.Source.name=="Demo Library"))).scalars().first():
            s.add(models.Source(name="Demo Library", path="Manga", enabled=True))
            await s.commit()
        plan = await perform_scan(s, dry_run=True)
        print(\"Dry-run summary\", json.dumps(plan.summary.model_dump(), indent=2))
        await perform_scan(s, dry_run=False)
asyncio.run(main())
PY
```
Observed dry-run summary on this machine:
```
{
  "archives_to_copy": 1,
  "galleries_to_zip": 2,
  "skipped_existing": 0,
  "duplicates": 0,
  "overwrites": 0
}
```
Resulting output structure (after the run): `dev-output/Manga/SeriesA/Chapter1.zip`, `dev-output/Manga/SeriesA/Chapter1/Chapter1.zip`, `dev-output/Manga/SeriesA/Chapter2/Chapter2.zip`.

## Behavior notes
- No writes ever occur under `/data`. Output/duplicates/config dirs are created at startup.
- Zips are built to `/config/tmp` and atomically moved into place.
- Duplicate handling: same-size dest skips; otherwise copies to `/duplicates` when mounted/enabled or renames with `_DUP_{timestamp}` in `/output`.
- Signatures (image count, bytes, newest mtime) are stored for gallery zips to decide overwrites when `update_gallery_zips` is enabled.
- Activity log is queryable via `/api/activity` and printed to stdout.
- Logging: base log at `/config/logs/galleryloom.log`; optional debug log at `/config/logs/galleryloom-debug.log` when `debug_logging` is enabled (toggle in Settings). Fetch logs via `/api/logs?level=info|debug` or use the dashboard Logs section.
- Debugging tips: turn on `debug_logging` in the Settings UI to capture per-action traces. Use the dashboard Logs pane or `curl http://host:8080/api/logs?level=debug` to tail recent entries. Disable when not needed to reduce noise/IO.

## Self-test
Run the lightweight harness to validate nested gallery handling and update decisions:
```
python scripts/self_test.py
```

## Changelog
- 0.2.0: Unraid-ready paths + PUID/PGID, rotating logs, system endpoint, diff API/UI, LANraragi flatten + cbz option, foldercopy output mode, improved skip reasons, self-test harness.
- 0.2.1: Added auto-scan watcher + interval controls, expanded docs for Unraid GUI/CLI install, debug logging notes.
