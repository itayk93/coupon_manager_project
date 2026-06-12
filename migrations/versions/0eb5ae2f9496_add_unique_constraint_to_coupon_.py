"""add unique constraint to coupon transactions

Revision ID: 0eb5ae2f9496
Revises: add_auto_update_runs
Create Date: 2026-02-04 10:19:00.145841

NEUTRALIZED (2026-06-12): this revision was auto-generated against a drifted
database and contained destructive operations — it dropped four live tables
(daily_email_status, bot_settings, notification_settings,
telegram_users_audit_log) and rewrote dozens of columns that were never meant
to change. It was never applied to production; the database was stamped past
it after the only intended change (the uq_coupon_transaction_ref unique
constraint, handled by revision 'add_unique_constraint') was applied manually.

It is kept as an intentional no-op so the revision chain stays intact for
fresh databases. Do NOT restore the original operations.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0eb5ae2f9496'
down_revision = 'add_auto_update_runs'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
