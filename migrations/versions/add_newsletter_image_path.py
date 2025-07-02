"""Add image_path field to Newsletter model

Revision ID: add_newsletter_image_path
Revises: add_newsletter_image
Create Date: 2025-07-01 23:08:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_newsletter_image_path'
down_revision = '81096b03fd20'
branch_labels = None
depends_on = None


def upgrade():
    # Add image_path column to newsletters table
    with op.batch_alter_table('newsletters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_path', sa.String(length=255), nullable=True))


def downgrade():
    # Remove image_path column from newsletters table
    with op.batch_alter_table('newsletters', schema=None) as batch_op:
        batch_op.drop_column('image_path')