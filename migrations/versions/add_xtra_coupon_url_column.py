"""Add xtra_coupon_url column to coupon table

Revision ID: add_xtra_url
Revises: add_xgiftcard_url
Create Date: 2025-01-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_xtra_url'
down_revision = 'c8301812ec94'
branch_labels = None
depends_on = None


def upgrade():
    """Add xtra_coupon_url column to coupon table."""
    # Add the xtra_coupon_url column as a regular string
    # The encryption will be handled by the EncryptedString type decorator in the model
    with op.batch_alter_table('coupon', schema=None) as batch_op:
        batch_op.add_column(sa.Column('xtra_coupon_url', sa.String(length=255), nullable=True))


def downgrade():
    """Remove xtra_coupon_url column from coupon table."""
    with op.batch_alter_table('coupon', schema=None) as batch_op:
        batch_op.drop_column('xtra_coupon_url')