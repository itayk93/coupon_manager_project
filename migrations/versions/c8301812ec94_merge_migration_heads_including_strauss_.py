"""Merge migration heads including strauss_coupon_url

Revision ID: c8301812ec94
Revises: 97bc16fd57fa, add_coupon_sharing_tables, add_modern_newsletter_fields, add_strauss_coupon_url, ef0f1e525b3f
Create Date: 2025-08-02 09:03:44.141502

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8301812ec94'
down_revision = ('97bc16fd57fa', 'add_coupon_sharing_tables', 'add_modern_newsletter_fields', 'add_strauss_coupon_url', 'ef0f1e525b3f')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
