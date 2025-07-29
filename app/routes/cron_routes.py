from flask import Blueprint, render_template
import logging

logger = logging.getLogger(__name__)

cron_bp = Blueprint('cron_bp', __name__)

@cron_bp.route('/cron/run-coupon-task/A5d8F2gH3jK4lPq9wE7rT1zU0iO/')
def cron_task():
    """A view for the cron job, accessible without login."""
    logger.info("Cron task endpoint was accessed.")
    return render_template('cron_task.html')

@cron_bp.route('/cron/test')
def cron_test():
    """A simple test route."""
    logger.info("Cron test endpoint was accessed.")
    return "Cron blueprint is working!"
