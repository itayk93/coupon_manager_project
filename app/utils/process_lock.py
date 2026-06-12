# app/utils/process_lock.py
"""
נעילה בין-תהליכית לשירותי singleton (בוט טלגרם, scheduler).

gunicorn מרים כמה workers שכולם מריצים את אותו קוד אתחול; שירותים שמותר
שירוצו רק פעם אחת לכל שרת חייבים נעילה. הנעילה מבוססת flock ומשתחררת
אוטומטית כשהתהליך מת — אין סכנת נעילה תקועה.
"""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Keep references so the file descriptors (and the locks) live as long as the process.
_held_locks = {}


def acquire_singleton_lock(name: str) -> bool:
    """
    מנסה לתפוס נעילה בשם נתון. מחזיר True אם התהליך הזה זכה בנעילה,
    False אם תהליך אחר כבר מחזיק אותה. ללא חסימה (non-blocking).
    """
    if name in _held_locks:
        return True

    lock_path = os.path.join(tempfile.gettempdir(), f"coupon_manager_{name}.lock")
    try:
        import fcntl

        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            logger.info(f"Singleton lock '{name}' is held by another process; skipping.")
            return False
        os.write(fd, str(os.getpid()).encode())
        _held_locks[name] = fd
        return True
    except ImportError:
        # Non-POSIX platform (Windows) — no flock; assume single process.
        logger.warning(f"flock unavailable; assuming single process for '{name}'.")
        return True
    except Exception as e:
        # A lock failure must never take the app down with it.
        logger.error(f"Failed to acquire singleton lock '{name}': {e}")
        return False
