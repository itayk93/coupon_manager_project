"""Add coupon sharing tables

Revision ID: add_coupon_sharing_tables
Revises: b43b720fccd5
Create Date: 2025-07-05 10:08:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_coupon_sharing_tables'
down_revision = 'b43b720fccd5'
branch_labels = None
depends_on = None


def upgrade():
    # Create coupon_shares table
    op.create_table('coupon_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('coupon_id', sa.Integer(), nullable=False),
        sa.Column('shared_by_user_id', sa.Integer(), nullable=False),
        sa.Column('shared_with_user_id', sa.Integer(), nullable=True),
        sa.Column('share_token', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('share_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revocation_token', sa.String(length=255), nullable=True),
        sa.Column('revocation_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revocation_requested_by', sa.Integer(), nullable=True),
        sa.Column('revocation_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['coupon_id'], ['coupon.id'], ),
        sa.ForeignKeyConstraint(['revocation_requested_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['shared_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['shared_with_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('share_token')
    )
    
    # Create coupon_active_viewers table
    op.create_table('coupon_active_viewers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('coupon_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('last_activity', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('session_id', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['coupon_id'], ['coupon.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('coupon_active_viewers')
    op.drop_table('coupon_shares')