"""Add last_scraped column to coupon table

Revision ID: ec8844d4ccd4
Revises: b0e172660f29
Create Date: 2025-10-07 19:01:35.675881

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec8844d4ccd4'
down_revision = 'b0e172660f29'
branch_labels = None
depends_on = None


def upgrade():
    # Add last_scraped column to coupon table
    op.add_column('coupon', sa.Column('last_scraped', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Remove last_scraped column from coupon table
    op.drop_column('coupon', 'last_scraped')
