#!/usr/bin/env bash
set -euo pipefail

APP_USER=gloom
APP_GROUP=gloom
PUID=${PUID:-0}
PGID=${PGID:-0}

# Create user/group matching requested IDs when non-root.
if [[ "$PGID" != "0" ]]; then
  if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -o -g "$PGID" "$APP_GROUP" >/dev/null 2>&1 || true
  fi
fi

if [[ "$PUID" != "0" ]]; then
  if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd -o -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin "$APP_USER" >/dev/null 2>&1 || true
  fi

  usermod -o -u "$PUID" -g "$PGID" "$APP_USER" >/dev/null 2>&1 || true
fi

# Ensure expected mount points exist and ownership matches runtime user.
for dir in /config /output /duplicates; do
  mkdir -p "$dir"
  if [[ "$PUID" != "0" || "$PGID" != "0" ]]; then
    chown "$PUID":"$PGID" "$dir" || true
  fi
done

if [[ "$PUID" != "0" || "$PGID" != "0" ]]; then
  exec gosu "$PUID":"$PGID" "$@"
else
  exec "$@"
fi
