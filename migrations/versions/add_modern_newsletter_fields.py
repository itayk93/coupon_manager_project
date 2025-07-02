"""Add modern newsletter fields

Revision ID: add_modern_newsletter_fields
Revises: 
Create Date: 2025-07-02 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_modern_newsletter_fields'
down_revision = 'add_newsletter_image_path'
branch_labels = None
depends_on = None


def upgrade():
    # הוספת השדות החדשים לטבלת newsletters
    with op.batch_alter_table('newsletters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('greeting_title', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('greeting_content', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('highlight_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('highlight_icon', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('footer_message', sa.Text(), nullable=True))


def downgrade():
    # הסרת השדות החדשים
    with op.batch_alter_table('newsletters', schema=None) as batch_op:
        batch_op.drop_column('footer_message')
        batch_op.drop_column('highlight_icon')
        batch_op.drop_column('highlight_text')
        batch_op.drop_column('greeting_content')
        batch_op.drop_column('greeting_title')