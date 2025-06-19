"""Add performance indexes

Revision ID: add_performance_indexes
Revises: 
Create Date: 2025-06-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_performance_indexes'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add indexes for better query performance
    try:
        # Index on user_id for coupons (most common filter)
        op.create_index('idx_coupon_user_id', 'coupon', ['user_id'])
    except:
        pass
        
    try:
        # Composite index for user_id + is_for_sale (common combination)
        op.create_index('idx_coupon_user_sale', 'coupon', ['user_id', 'is_for_sale'])
    except:
        pass
        
    try:
        # Index on status for filtering active coupons
        op.create_index('idx_coupon_status', 'coupon', ['status'])
    except:
        pass
        
    try:
        # Index on company for grouping statistics
        op.create_index('idx_coupon_company', 'coupon', ['company'])
    except:
        pass
        
    try:
        # Index on date_added for timeline queries
        op.create_index('idx_coupon_date_added', 'coupon', ['date_added'])
    except:
        pass
        
    try:
        # Index on expiration for expiration queries
        op.create_index('idx_coupon_expiration', 'coupon', ['expiration'])
    except:
        pass
        
    try:
        # Composite index for the most common query pattern
        op.create_index('idx_coupon_user_status_sale', 'coupon', ['user_id', 'status', 'is_for_sale'])
    except:
        pass

def downgrade():
    # Remove indexes
    try:
        op.drop_index('idx_coupon_user_status_sale', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_expiration', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_date_added', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_company', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_status', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_user_sale', 'coupon')
    except:
        pass
        
    try:
        op.drop_index('idx_coupon_user_id', 'coupon')
    except:
        pass