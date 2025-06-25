"""Merge heads before adding user preferences

Revision ID: f78a2e3a929a
Revises: 81096b03fd20, add_id_to_user_tour_progress, newsletter_update, add_performance_indexes
Create Date: 2025-06-22 23:18:20.093439

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f78a2e3a929a'
down_revision = ('81096b03fd20', 'add_id_to_user_tour_progress', 'newsletter_update', 'add_performance_indexes')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
