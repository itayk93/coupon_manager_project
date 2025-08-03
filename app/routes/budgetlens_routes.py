# app/routes/budgetlens_routes.py

import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import BankTransaction
from difflib import SequenceMatcher
import re

budgetlens_bp = Blueprint('budgetlens', __name__, url_prefix='/budgetlens')

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a, b).ratio()

def clean_business_name(name):
    """Clean and normalize business name for comparison"""
    if not name:
        return ""
    # Remove common prefixes and normalize Hebrew text
    name = str(name).strip()
    # Remove leading/trailing whitespace and common characters
    name = re.sub(r'^[\u200F\u200E\s]*', '', name)  # Remove RTL/LTR marks
    name = re.sub(r'[\u200F\u200E\s]*$', '', name)  # Remove RTL/LTR marks
    return name.lower()

def parse_date(date_str):
    """Parse date string in DD/MM/YYYY format"""
    try:
        if '/' in date_str:
            return datetime.strptime(date_str, '%d/%m/%Y').date()
        elif '-' in date_str:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        pass
    return None

def parse_amount(amount_str):
    """Parse amount string and convert to float"""
    try:
        if isinstance(amount_str, str):
            # Remove commas and convert to float
            amount_str = amount_str.replace(',', '')
        return float(amount_str)
    except:
        return None

@budgetlens_bp.route('/')
@login_required
def budgetlens_comparison():
    """Display BudgetLens comparison page"""
    return render_template('budgetlens/comparison.html')

@budgetlens_bp.route('/upload', methods=['POST'])
@login_required
def upload_budgetlens_file():
    """Handle BudgetLens CSV file upload and comparison"""
    try:
        if 'budgetlens_file' not in request.files:
            flash('לא נבחר קובץ', 'danger')
            return redirect(url_for('budgetlens.budgetlens_comparison'))
        
        file = request.files['budgetlens_file']
        if file.filename == '':
            flash('לא נבחר קובץ', 'danger')
            return redirect(url_for('budgetlens.budgetlens_comparison'))
        
        if not file.filename.lower().endswith('.csv'):
            flash('יש להעלות קובץ CSV בלבד', 'danger')
            return redirect(url_for('budgetlens.budgetlens_comparison'))

        # Get date range from form
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        
        if not start_date_str or not end_date_str:
            flash('יש להזין טווח תאריכים', 'danger')
            return redirect(url_for('budgetlens.budgetlens_comparison'))
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # Read CSV file
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.DictReader(stream)
        
        budgetlens_transactions = []
        for row in csv_reader:
            date = parse_date(row.get('תאריך התשלום', ''))
            if date and start_date <= date <= end_date:
                amount = parse_amount(row.get('סכום', ''))
                if amount is not None:
                    budgetlens_transactions.append({
                        'business_name': clean_business_name(row.get('שם העסק', '')),
                        'original_business_name': row.get('שם העסק', ''),
                        'date': date,
                        'amount': amount,
                        'payment_method': row.get('אמצעי התשלום', ''),
                        'notes': row.get('הערות', ''),
                        'category': row.get('קטגוריה בתזרים', '')
                    })
        
        # For now, we'll use sample data since the BankTransaction table doesn't exist yet
        # This simulates the data structure you provided
        sample_db_transactions = [
            {
                'id': '39b54d83-f061-4adb-8026-7872c6698623',
                'business_name': clean_business_name('‫העברה ‫דיסקינד פנ'),
                'original_business_name': '‫העברה ‫דיסקינד פנ',
                'date': datetime.strptime('2025-07-28', '%Y-%m-%d').date(),
                'amount': -50.0,
                'payment_method': 'bank_yahav',
                'notes': 'תשלום על מזרון ושמשיה בהרצליה',
                'category': 'הוצאות משתנות'
            },
            {
                'id': '35289b9e-745c-4b52-85c5-b9e8ddacea3f',
                'business_name': clean_business_name('‫מכירה ‫(00) דולפין ‫אינטרנט'),
                'original_business_name': '‫מכירה ‫(00) דולפין ‫אינטרנט',
                'date': datetime.strptime('2025-07-31', '%Y-%m-%d').date(),
                'amount': 4021.49,
                'payment_method': 'bank_yahav',
                'notes': 'מכירה של קרן כספית בשביל הביטוח לאופנוע',
                'category': 'הכנסות לא תזרימיות'
            },
            {
                'id': '86ba5075-0376-4574-a1d1-f769136e0035',
                'business_name': clean_business_name('‫משכורת ‫09-שביט סופטוור'),
                'original_business_name': '‫משכורת ‫09-שביט סופטוור',
                'date': datetime.strptime('2025-08-02', '%Y-%m-%d').date(),
                'amount': 15869.53,
                'payment_method': 'bank_yahav',
                'notes': '',
                'category': 'הכנסות קבועות'
            }
        ]
        
        # Filter sample data by date range
        db_trans_list = []
        for trans in sample_db_transactions:
            if start_date <= trans['date'] <= end_date:
                db_trans_list.append(trans)
        
        # Find missing transactions
        missing_transactions = []
        matched_transactions = []
        
        for bl_trans in budgetlens_transactions:
            best_match = None
            best_score = 0
            
            for db_trans in db_trans_list:
                # Check if same date and similar amount (within 5% tolerance)
                if (bl_trans['date'] == db_trans['date'] and 
                    abs(bl_trans['amount'] - db_trans['amount']) <= abs(bl_trans['amount']) * 0.05):
                    
                    # Calculate business name similarity
                    name_similarity = similarity(bl_trans['business_name'], db_trans['business_name'])
                    
                    if name_similarity > best_score:
                        best_score = name_similarity
                        best_match = db_trans
            
            # Consider it missing if no good match found (similarity < 0.7)
            if best_score < 0.7:
                missing_transactions.append(bl_trans)
            else:
                matched_transactions.append({
                    'budgetlens': bl_trans,
                    'database': best_match,
                    'similarity': best_score
                })
        
        return render_template('budgetlens/results.html',
                             missing_transactions=missing_transactions,
                             matched_transactions=matched_transactions,
                             total_budgetlens=len(budgetlens_transactions),
                             total_database=len(db_trans_list),
                             start_date=start_date,
                             end_date=end_date)
        
    except Exception as e:
        flash(f'שגיאה בעיבוד הקובץ: {str(e)}', 'danger')
        return redirect(url_for('budgetlens.budgetlens_comparison'))