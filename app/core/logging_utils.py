import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False
_current_debug = False


def setup_logging(config_root: Path, debug_enabled: bool = False):
    """
    Configure logging to stdout, a primary log file, and an optional debug log file under /config/logs.
    Safe to call multiple times.
    """
    global _configured
    global _current_debug
    if _configured and _current_debug == debug_enabled:
        return
    _current_debug = debug_enabled

    fmt = "[%(levelname)s] %(asctime)s %(name)s :: %(message)s"
    log_dir = config_root / "logs"
    handlers: list[logging.Handler] = []
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - startup-only path
        print(f"[GalleryLoom] Could not create log dir: {exc}")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    handlers.append(console_handler)

    try:
        info_file = RotatingFileHandler(
            log_dir / "galleryloom.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        info_file.setLevel(logging.INFO)
        handlers.append(info_file)
    except Exception as exc:  # pragma: no cover - startup-only path
        print(f"[GalleryLoom] Could not set up main log file: {exc}")

    if debug_enabled:
        try:
            debug_file = RotatingFileHandler(
                log_dir / "galleryloom-debug.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
            )
            debug_file.setLevel(logging.DEBUG)
            handlers.append(debug_file)
        except Exception as exc:  # pragma: no cover - startup-only path
            print(f"[GalleryLoom] Could not set up debug log file: {exc}")

    logging.basicConfig(
        level=logging.DEBUG if debug_enabled else logging.INFO,
        format=fmt,
        handlers=handlers,
        force=True,
    )
    _configured = True


def reconfigure_logging(config_root: Path, debug_enabled: bool):
    """Rebuild logging stack when debug toggle changes."""
    global _configured
    _configured = False
    setup_logging(config_root, debug_enabled)
