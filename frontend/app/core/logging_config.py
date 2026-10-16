"""Central application logging: daily rolling file handler plus console, runtime-adjustable level.

A new log file is started every day at midnight in logs/; rotated files are
suffixed with their date (app.log.2026-08-06). The active level is persisted so
it survives restarts and can be changed live from the admin settings page.
"""

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / 'logs'
LOG_FILE = LOG_DIR / 'app.log'
_LEVEL_FILE = LOG_DIR / '.log_level'

# Selectable levels, ordered from most to least verbose.
LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
_DEFAULT_LEVEL = 'INFO'

_BACKUP_COUNT = 0            # 0 = keep every daily log file forever

_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'

logger = logging.getLogger(__name__)


class _DrawerTeardownFilter(logging.Filter):
    """Drop the drawer's JS-request timeouts at page teardown.

    NiceGUI's Drawer widget asks the browser whether it is open on every
    client connect (an AWAITED JavaScript call with a 1 s timeout). When the
    page is torn down right then — F5, logout navigation, tab close — the
    answer never arrives and NiceGUI logs a full ERROR traceback per
    navigation burst. Pure teardown noise: nothing to act on. We only drop
    records whose traceback goes through the drawer's own _request_value,
    so genuine JavaScript errors still surface.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != 'nicegui' or record.exc_info is None:
            return True
        if 'did not respond' not in str(record.getMessage()):
            return True
        tb = record.exc_info[2]
        while tb is not None:
            if tb.tb_frame.f_code.co_filename.endswith('elements/drawer.py'):
                return False
            tb = tb.tb_next
        return True


def _read_persisted_level() -> str:
    try:
        level = _LEVEL_FILE.read_text(encoding='utf-8').strip().upper()
        if level in LOG_LEVELS:
            return level
    except OSError:
        pass
    return _DEFAULT_LEVEL


def setup_logging() -> None:
    """Configure root logging with a rolling file handler and a console handler.

    Idempotent: safe to call more than once (e.g. under the dev auto-reloader)
    without stacking duplicate handlers.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(_read_persisted_level())

    # Silence the dev auto-reloader's change logs: writing them into logs/app.log
    # is itself a file change, which retriggers the watcher in an endless loop.
    logging.getLogger('watchfiles').setLevel(logging.WARNING)

    if any(getattr(h, '_app_handler', False) for h in root.handlers):
        return

    formatter = logging.Formatter(_FORMAT)

    # Rolls over at midnight; rotated files get a .YYYY-MM-DD suffix.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when='midnight', interval=1, backupCount=_BACKUP_COUNT, encoding='utf-8'
    )
    file_handler.suffix = '%Y-%m-%d'
    file_handler.setFormatter(formatter)
    file_handler._app_handler = True

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._app_handler = True

    # Applied to the handlers (not a logger) so both sinks drop the noise.
    noise = _DrawerTeardownFilter()
    file_handler.addFilter(noise)
    console.addFilter(noise)

    root.addHandler(file_handler)
    root.addHandler(console)
    logger.info('Logging initialised — level=%s, file=%s', get_log_level(), LOG_FILE)


def get_log_level() -> str:
    """Return the current root log level name (e.g. ``'INFO'``)."""
    return logging.getLevelName(logging.getLogger().level)


def set_log_level(level: str) -> bool:
    """Set and persist the root log level. Returns ``True`` when applied."""
    level = level.upper()
    if level not in LOG_LEVELS:
        return False
    logging.getLogger().setLevel(level)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _LEVEL_FILE.write_text(level, encoding='utf-8')
    except OSError:
        logger.warning('Could not persist log level to %s', _LEVEL_FILE)
    logger.info('Log level changed to %s', level)
    return True
