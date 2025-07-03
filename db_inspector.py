#!/usr/bin/env python3
"""
Database Inspector Script for Coupon Manager Project
====================================================

This script provides database inspection tools for checking user status
and performing basic database queries. It's specifically designed to help
administrators check user details and database status.

Usage:
    python db_inspector.py --user-email itayk93@gmail.com
    python db_inspector.py --user-id 1
    python db_inspector.py --all-users
    python db_inspector.py --stats
"""

import os
import sys
import argparse
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pandas as pd

# Load environment variables
load_dotenv()

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import models
from app.models import User, Coupon, Transaction, Notification
from app.extensions import db

def create_app():
    """Create a minimal Flask app for database access"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "default_secret_key")
    
    # Database configuration
    database_url = os.getenv("DATABASE_URL", "sqlite:///instance/app.db")
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        if '?' not in database_url:
            database_url += '?sslmode=require'
    
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def get_user_by_email(email):
    """Get user information by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if user:
            return {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_confirmed': user.is_confirmed,
                'is_admin': user.is_admin,
                'is_deleted': user.is_deleted,
                'slots': user.slots,
                'slots_automatic_coupons': user.slots_automatic_coupons,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None,
                'google_id': user.google_id,
                'newsletter_subscription': user.newsletter_subscription,
                'telegram_monthly_summary': user.telegram_monthly_summary,
                'days_since_register': user.days_since_register
            }
        return None
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None

def get_user_by_id(user_id):
    """Get user information by ID"""
    try:
        user = User.query.get(user_id)
        if user:
            return {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_confirmed': user.is_confirmed,
                'is_admin': user.is_admin,
                'is_deleted': user.is_deleted,
                'slots': user.slots,
                'slots_automatic_coupons': user.slots_automatic_coupons,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None,
                'google_id': user.google_id,
                'newsletter_subscription': user.newsletter_subscription,
                'telegram_monthly_summary': user.telegram_monthly_summary,
                'days_since_register': user.days_since_register
            }
        return None
    except Exception as e:
        print(f"Error getting user by ID: {e}")
        return None

def get_all_users(limit=10):
    """Get all users with optional limit"""
    try:
        users = User.query.limit(limit).all()
        users_list = []
        for user in users:
            users_list.append({
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_confirmed': user.is_confirmed,
                'is_admin': user.is_admin,
                'is_deleted': user.is_deleted,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None,
                'days_since_register': user.days_since_register
            })
        return users_list
    except Exception as e:
        print(f"Error getting all users: {e}")
        return []

def get_user_stats(user_id):
    """Get user statistics including coupons and transactions"""
    try:
        user = User.query.get(user_id)
        if not user:
            return None
        
        # Get user's coupons
        coupons = Coupon.query.filter_by(user_id=user_id).all()
        
        # Get user's transactions as seller
        transactions_sold = Transaction.query.filter_by(seller_id=user_id).all()
        
        # Get user's transactions as buyer
        transactions_bought = Transaction.query.filter_by(buyer_id=user_id).all()
        
        # Get user's notifications
        notifications = Notification.query.filter_by(user_id=user_id).all()
        
        return {
            'user_info': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_admin': user.is_admin,
                'is_confirmed': user.is_confirmed,
                'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else None
            },
            'coupons_count': len(coupons),
            'active_coupons': len([c for c in coupons if c.status == 'פעיל']),
            'expired_coupons': len([c for c in coupons if c.status == 'פג תוקף']),
            'used_coupons': len([c for c in coupons if c.status == 'נוצל']),
            'total_coupon_value': sum(c.value for c in coupons),
            'total_coupon_cost': sum(c.cost for c in coupons),
            'transactions_sold_count': len(transactions_sold),
            'transactions_bought_count': len(transactions_bought),
            'notifications_count': len(notifications),
            'unread_notifications': len([n for n in notifications if not n.viewed])
        }
    except Exception as e:
        print(f"Error getting user stats: {e}")
        return None

def get_database_stats():
    """Get general database statistics"""
    try:
        total_users = User.query.count()
        confirmed_users = User.query.filter_by(is_confirmed=True).count()
        admin_users = User.query.filter_by(is_admin=True).count()
        deleted_users = User.query.filter_by(is_deleted=True).count()
        
        total_coupons = Coupon.query.count()
        active_coupons = Coupon.query.filter_by(status='פעיל').count()
        expired_coupons = Coupon.query.filter_by(status='פג תוקף').count()
        used_coupons = Coupon.query.filter_by(status='נוצל').count()
        
        total_transactions = Transaction.query.count()
        completed_transactions = Transaction.query.filter_by(status='הושלמה').count()
        
        total_notifications = Notification.query.count()
        unread_notifications = Notification.query.filter_by(viewed=False).count()
        
        return {
            'users': {
                'total': total_users,
                'confirmed': confirmed_users,
                'admin': admin_users,
                'deleted': deleted_users
            },
            'coupons': {
                'total': total_coupons,
                'active': active_coupons,
                'expired': expired_coupons,
                'used': used_coupons
            },
            'transactions': {
                'total': total_transactions,
                'completed': completed_transactions
            },
            'notifications': {
                'total': total_notifications,
                'unread': unread_notifications
            }
        }
    except Exception as e:
        print(f"Error getting database stats: {e}")
        return None

def print_user_info(user_info):
    """Print user information in a formatted way"""
    if not user_info:
        print("User not found.")
        return
    
    print("=" * 50)
    print("USER INFORMATION")
    print("=" * 50)
    print(f"ID: {user_info['id']}")
    print(f"Email: {user_info['email']}")
    print(f"Name: {user_info['first_name']} {user_info['last_name']}")
    print(f"Admin: {'Yes' if user_info['is_admin'] else 'No'}")
    print(f"Confirmed: {'Yes' if user_info['is_confirmed'] else 'No'}")
    print(f"Deleted: {'Yes' if user_info['is_deleted'] else 'No'}")
    print(f"Slots: {user_info['slots']}")
    print(f"Automation Slots: {user_info['slots_automatic_coupons']}")
    print(f"Created: {user_info['created_at']}")
    print(f"Days since registration: {user_info['days_since_register']}")
    print(f"Google ID: {user_info['google_id'] or 'Not connected'}")
    print(f"Newsletter subscription: {'Yes' if user_info['newsletter_subscription'] else 'No'}")
    print(f"Telegram summary: {'Yes' if user_info['telegram_monthly_summary'] else 'No'}")
    print("=" * 50)

def print_user_stats(stats):
    """Print user statistics in a formatted way"""
    if not stats:
        print("User stats not found.")
        return
    
    print("=" * 50)
    print("USER STATISTICS")
    print("=" * 50)
    print(f"User: {stats['user_info']['first_name']} {stats['user_info']['last_name']} ({stats['user_info']['email']})")
    print(f"Total Coupons: {stats['coupons_count']}")
    print(f"  - Active: {stats['active_coupons']}")
    print(f"  - Expired: {stats['expired_coupons']}")
    print(f"  - Used: {stats['used_coupons']}")
    print(f"Total Coupon Value: ₪{stats['total_coupon_value']:.2f}")
    print(f"Total Coupon Cost: ₪{stats['total_coupon_cost']:.2f}")
    print(f"Transactions Sold: {stats['transactions_sold_count']}")
    print(f"Transactions Bought: {stats['transactions_bought_count']}")
    print(f"Notifications: {stats['notifications_count']} (Unread: {stats['unread_notifications']})")
    print("=" * 50)

def print_database_stats(stats):
    """Print database statistics in a formatted way"""
    if not stats:
        print("Database stats not found.")
        return
    
    print("=" * 50)
    print("DATABASE STATISTICS")
    print("=" * 50)
    print("USERS:")
    print(f"  Total: {stats['users']['total']}")
    print(f"  Confirmed: {stats['users']['confirmed']}")
    print(f"  Admin: {stats['users']['admin']}")
    print(f"  Deleted: {stats['users']['deleted']}")
    print()
    print("COUPONS:")
    print(f"  Total: {stats['coupons']['total']}")
    print(f"  Active: {stats['coupons']['active']}")
    print(f"  Expired: {stats['coupons']['expired']}")
    print(f"  Used: {stats['coupons']['used']}")
    print()
    print("TRANSACTIONS:")
    print(f"  Total: {stats['transactions']['total']}")
    print(f"  Completed: {stats['transactions']['completed']}")
    print()
    print("NOTIFICATIONS:")
    print(f"  Total: {stats['notifications']['total']}")
    print(f"  Unread: {stats['notifications']['unread']}")
    print("=" * 50)

def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(description='Database Inspector for Coupon Manager')
    parser.add_argument('--user-email', help='Get user information by email')
    parser.add_argument('--user-id', type=int, help='Get user information by ID')
    parser.add_argument('--all-users', action='store_true', help='Get all users (limited to 10)')
    parser.add_argument('--stats', action='store_true', help='Get database statistics')
    parser.add_argument('--user-stats', type=int, help='Get detailed statistics for a user by ID')
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    # Create Flask app context
    app = create_app()
    
    with app.app_context():
        if args.user_email:
            user_info = get_user_by_email(args.user_email)
            print_user_info(user_info)
            
        elif args.user_id:
            user_info = get_user_by_id(args.user_id)
            print_user_info(user_info)
            
        elif args.all_users:
            users = get_all_users()
            print("=" * 50)
            print("ALL USERS (Limited to 10)")
            print("=" * 50)
            for user in users:
                print(f"ID: {user['id']}, Email: {user['email']}, Name: {user['first_name']} {user['last_name']}, Admin: {'Yes' if user['is_admin'] else 'No'}, Confirmed: {'Yes' if user['is_confirmed'] else 'No'}")
            print("=" * 50)
            
        elif args.stats:
            stats = get_database_stats()
            print_database_stats(stats)
            
        elif args.user_stats:
            stats = get_user_stats(args.user_stats)
            print_user_stats(stats)

if __name__ == '__main__':
    main()