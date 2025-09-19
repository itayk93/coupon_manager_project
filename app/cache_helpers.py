# app/cache_helpers.py
from functools import wraps
from flask import request
from flask_login import current_user
from app.extensions import cache


def cache_key_with_user_id(prefix=""):
    """Generate cache key with user ID"""
    user_id = current_user.id if current_user.is_authenticated else "anonymous"
    return f"{prefix}_user_{user_id}"


def cached_user_data(timeout=300, key_prefix=""):
    """Decorator for caching user-specific data"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            cache_key = cache_key_with_user_id(key_prefix or f.__name__)
            result = cache.get(cache_key)
            
            if result is None:
                result = f(*args, **kwargs)
                cache.set(cache_key, result, timeout=timeout)
            
            return result
        return decorated_function
    return decorator


def clear_user_cache(user_id, prefixes=None):
    """Clear all cache entries for a specific user"""
    if prefixes is None:
        prefixes = ['index_stats', 'marketplace_data', 'user_coupons']
    
    for prefix in prefixes:
        cache_key = f"{prefix}_user_{user_id}"
        cache.delete(cache_key)


def cache_for_minutes(minutes):
    """Simple cache decorator for specified minutes"""
    def decorator(f):
        @cache.memoize(timeout=minutes * 60)
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@cache.memoize(timeout=600)  # 10 minutes
def get_companies_with_counts():
    """Get companies data with coupon counts - cached"""
    from app.models import Company
    return Company.query.all()


@cache.memoize(timeout=300)  # 5 minutes
def get_tags_data():
    """Get tags data - cached"""
    from app.models import Tag
    return Tag.query.all()


def invalidate_user_caches(user_id):
    """Invalidate all user-related caches"""
    # Clear memoized functions
    from app.models import Coupon, User
    
    # Clear user's coupon cache
    cache.delete_memoized(Coupon.get_user_coupons_cached, user_id)
    
    # Clear user cache if needed
    user = User.query.get(user_id)
    if user:
        cache.delete_memoized(User.get_by_email_cached, user.email)
    
    # Clear user-specific caches
    clear_user_cache(user_id)