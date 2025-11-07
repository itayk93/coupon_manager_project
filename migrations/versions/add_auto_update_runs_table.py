"""Add auto_update_runs table

Revision ID: add_auto_update_runs
Revises: ec8844d4ccd4
Create Date: 2025-11-06 23:40:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_auto_update_runs'
down_revision = 'ec8844d4ccd4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'auto_update_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('triggered_by_user_id', sa.Integer(), nullable=True),
        sa.Column('run_type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('job_id', sa.String(length=100), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ),
    )
    op.create_index('ix_auto_update_runs_started_at', 'auto_update_runs', ['started_at'])
    op.create_index('ix_auto_update_runs_status', 'auto_update_runs', ['status'])


def downgrade():
    op.drop_index('ix_auto_update_runs_status', table_name='auto_update_runs')
    op.drop_index('ix_auto_update_runs_started_at', table_name='auto_update_runs')
    op.drop_table('auto_update_runs')

