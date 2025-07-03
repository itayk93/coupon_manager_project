#!/usr/bin/env python3
"""
SQL Query Tool for Coupon Manager Project
==========================================

This script allows running direct SQL queries against the database.
Use with caution as it provides direct database access.

Usage:
    python sql_query_tool.py --query "SELECT * FROM users WHERE email = 'itayk93@gmail.com'"
    python sql_query_tool.py --predefined user_by_email --email "itayk93@gmail.com"
    python sql_query_tool.py --predefined admin_users
    python sql_query_tool.py --predefined user_coupons --user_id 1
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from flask import Flask
from sqlalchemy import create_engine, text
import pandas as pd

# Load environment variables
load_dotenv()

def create_engine_connection():
    """Create database engine connection"""
    database_url = os.getenv("DATABASE_URL", "sqlite:///instance/app.db")
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        if '?' not in database_url:
            database_url += '?sslmode=require'
    
    engine = create_engine(database_url)
    return engine

def execute_query(query, params=None):
    """Execute a SQL query and return results"""
    try:
        engine = create_engine_connection()
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            if result.returns_rows:
                columns = result.keys()
                rows = result.fetchall()
                return pd.DataFrame(rows, columns=columns)
            else:
                return f"Query executed successfully. Rows affected: {result.rowcount}"
    except Exception as e:
        return f"Error executing query: {e}"

def get_predefined_queries():
    """Return a dictionary of predefined useful queries"""
    return {
        'user_by_email': {
            'query': """
                SELECT id, email, first_name, last_name, is_admin, is_confirmed, 
                       is_deleted, slots, slots_automatic_coupons, created_at
                FROM users 
                WHERE email = :email
            """,
            'params': ['email']
        },
        'admin_users': {
            'query': """
                SELECT id, email, first_name, last_name, is_confirmed, 
                       is_deleted, created_at
                FROM users 
                WHERE is_admin = true
            """,
            'params': []
        },
        'user_coupons': {
            'query': """
                SELECT id, code, company, value, cost, status, expiration, 
                       date_added, used_value
                FROM coupon 
                WHERE user_id = :user_id
                ORDER BY date_added DESC
            """,
            'params': ['user_id']
        },
        'user_notifications': {
            'query': """
                SELECT id, message, timestamp, viewed, hide_from_view
                FROM notifications 
                WHERE user_id = :user_id
                ORDER BY timestamp DESC
            """,
            'params': ['user_id']
        },
        'recent_users': {
            'query': """
                SELECT id, email, first_name, last_name, is_admin, is_confirmed, 
                       created_at
                FROM users 
                WHERE is_deleted = false
                ORDER BY created_at DESC 
                LIMIT 10
            """,
            'params': []
        },
        'coupon_summary': {
            'query': """
                SELECT 
                    status,
                    COUNT(*) as count,
                    SUM(value) as total_value,
                    SUM(cost) as total_cost
                FROM coupon 
                GROUP BY status
            """,
            'params': []
        },
        'user_coupon_stats': {
            'query': """
                SELECT 
                    u.id,
                    u.email,
                    u.first_name,
                    u.last_name,
                    COUNT(c.id) as total_coupons,
                    SUM(CASE WHEN c.status = 'פעיל' THEN 1 ELSE 0 END) as active_coupons,
                    SUM(CASE WHEN c.status = 'נוצל' THEN 1 ELSE 0 END) as used_coupons,
                    SUM(CASE WHEN c.status = 'פג תוקף' THEN 1 ELSE 0 END) as expired_coupons,
                    SUM(c.value) as total_value,
                    SUM(c.cost) as total_cost
                FROM users u
                LEFT JOIN coupon c ON u.id = c.user_id
                WHERE u.id = :user_id
                GROUP BY u.id, u.email, u.first_name, u.last_name
            """,
            'params': ['user_id']
        },
        'companies_summary': {
            'query': """
                SELECT 
                    company,
                    COUNT(*) as coupon_count,
                    SUM(value) as total_value,
                    AVG(value) as avg_value,
                    SUM(cost) as total_cost,
                    AVG(cost) as avg_cost
                FROM coupon 
                GROUP BY company
                ORDER BY coupon_count DESC
            """,
            'params': []
        },
        'expired_coupons': {
            'query': """
                SELECT 
                    c.id,
                    c.code,
                    c.company,
                    c.value,
                    c.expiration,
                    u.email,
                    u.first_name,
                    u.last_name
                FROM coupon c
                JOIN users u ON c.user_id = u.id
                WHERE c.expiration < CURRENT_DATE
                ORDER BY c.expiration DESC
            """,
            'params': []
        },
        'telegram_connected_users': {
            'query': """
                SELECT 
                    u.id,
                    u.email,
                    u.first_name,
                    u.last_name,
                    t.telegram_chat_id,
                    t.telegram_username,
                    t.is_active,
                    t.is_verified,
                    t.created_at
                FROM users u
                JOIN telegram_users t ON u.id = t.user_id
                WHERE t.is_active = true
                ORDER BY t.created_at DESC
            """,
            'params': []
        }
    }

def print_dataframe(df, title="Query Results"):
    """Print DataFrame in a formatted way"""
    print("=" * 80)
    print(title)
    print("=" * 80)
    if isinstance(df, pd.DataFrame):
        if df.empty:
            print("No results found.")
        else:
            print(df.to_string(index=False, max_rows=50))
            if len(df) > 50:
                print(f"\n... and {len(df) - 50} more rows")
    else:
        print(df)
    print("=" * 80)

def main():
    """Main function to handle command line arguments"""
    parser = argparse.ArgumentParser(description='SQL Query Tool for Coupon Manager')
    parser.add_argument('--query', help='Execute a custom SQL query')
    parser.add_argument('--predefined', help='Execute a predefined query', 
                       choices=list(get_predefined_queries().keys()))
    parser.add_argument('--email', help='Email parameter for predefined queries')
    parser.add_argument('--user_id', type=int, help='User ID parameter for predefined queries')
    parser.add_argument('--list-queries', action='store_true', help='List all predefined queries')
    
    args = parser.parse_args()
    
    if args.list_queries:
        print("Available predefined queries:")
        print("=" * 50)
        queries = get_predefined_queries()
        for name, info in queries.items():
            params_str = ", ".join(info['params']) if info['params'] else "None"
            print(f"Name: {name}")
            print(f"Parameters: {params_str}")
            description = info['query'].strip().split('\n')[0]
            print(f"Description: {description}")
            print("-" * 30)
        return
    
    if not args.query and not args.predefined:
        parser.print_help()
        return
    
    if args.query:
        # Execute custom query
        result = execute_query(args.query)
        print_dataframe(result, "Custom Query Results")
        
    elif args.predefined:
        # Execute predefined query
        queries = get_predefined_queries()
        if args.predefined not in queries:
            print(f"Unknown predefined query: {args.predefined}")
            return
        
        query_info = queries[args.predefined]
        params = {}
        
        # Collect required parameters
        for param in query_info['params']:
            if param == 'email' and args.email:
                params['email'] = args.email
            elif param == 'user_id' and args.user_id:
                params['user_id'] = args.user_id
            else:
                print(f"Missing required parameter: {param}")
                return
        
        result = execute_query(query_info['query'], params)
        print_dataframe(result, f"Predefined Query Results: {args.predefined}")

if __name__ == '__main__':
    main()