"""merge heads for unique constraint

Revision ID: 6b5676ac5bc0
Revises: 0eb5ae2f9496, add_unique_constraint
Create Date: 2026-02-04 10:20:01.515602

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b5676ac5bc0'
down_revision = ('0eb5ae2f9496', 'add_unique_constraint')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
