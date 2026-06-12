# app/utils/db_utils.py
"""
עזרי DB לשימוש בכל ה-routes.
"""
import logging

from app.extensions import db

logger = logging.getLogger(__name__)


def safe_commit() -> bool:
    """
    commit עם rollback אוטומטי בכשל, כדי שה-session לא יישאר במצב שבור.
    מחזיר True בהצלחה, False בכשל (השגיאה נרשמת ללוג).
    """
    try:
        db.session.commit()
        return True
    except Exception:
        logger.exception("db.session.commit() failed; rolling back")
        db.session.rollback()
        return False
