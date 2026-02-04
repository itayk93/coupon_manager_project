"""Add unique constraint to coupon transactions

Revision ID: add_unique_constraint
Revises: add_auto_update_runs
Create Date: 2026-02-04 10:18:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_unique_constraint'
down_revision = 'add_auto_update_runs'
branch_labels = None
depends_on = None


def upgrade():
    # Create the unique constraint
    try:
        op.create_unique_constraint('uq_coupon_transaction_ref', 'coupon_transaction', ['coupon_id', 'reference_number'])
    except Exception as e:
        print(f"Error creating constraint (might already exist?): {e}")


def downgrade():
    op.drop_constraint('uq_coupon_transaction_ref', 'coupon_transaction', type_='unique')
