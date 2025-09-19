# admin_scheduler_routes.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.models import ScheduledTask, TaskExecutionLog, Coupon, db
from app.extensions import db
from datetime import datetime, time
import json

admin_scheduler_bp = Blueprint("admin_scheduler_bp", __name__, url_prefix="/admin/scheduler")

def admin_required(f):
    """Decorator לוודא שרק מנהלים יכולים לגשת"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("אין לך הרשאה לצפות בדף זה.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function

@admin_scheduler_bp.route("/")
@login_required
@admin_required
def scheduler_dashboard():
    """מסך ראשי לניהול תזמון"""
    tasks = ScheduledTask.query.order_by(ScheduledTask.created_at.desc()).all()
    
    # חישוב ההפעלה הבאה לכל משימה
    for task in tasks:
        if task.is_active:
            task.calculate_next_run()
    
    db.session.commit()
    
    return render_template("admin/admin_scheduler.html", tasks=tasks)

@admin_scheduler_bp.route("/create", methods=["GET", "POST"])
@login_required
@admin_required
def create_task():
    """יצירת משימה חדשה"""
    if request.method == "POST":
        try:
            # קבלת נתונים מהטופס
            task_name = request.form.get("task_name")
            task_type = request.form.get("task_type")
            description = request.form.get("description")
            
            # זמן הפעלה
            execution_hour = int(request.form.get("execution_hour", 0))
            execution_minute = int(request.form.get("execution_minute", 0))
            execution_time = time(execution_hour, execution_minute)
            
            # סוג תזמון
            schedule_type = request.form.get("schedule_type")
            
            # בניית הגדרות התזמון
            schedule_details = {}
            
            if schedule_type == "weekly":
                schedule_details["weekday"] = int(request.form.get("weekday", 0))
            elif schedule_type == "monthly":
                schedule_details["day"] = int(request.form.get("monthly_day", 1))
            elif schedule_type == "specific_date":
                schedule_details["date"] = request.form.get("specific_date")
            
            # יצירת המשימה
            task = ScheduledTask(
                task_name=task_name,
                task_type=task_type,
                schedule_type=schedule_type,
                execution_time=execution_time,
                description=description,
                created_by_user_id=current_user.id
            )
            
            task.set_schedule_details(schedule_details)
            task.calculate_next_run()
            
            db.session.add(task)
            db.session.commit()
            
            flash(f"המשימה '{task_name}' נוצרה בהצלחה!", "success")
            return redirect(url_for("admin_scheduler_bp.scheduler_dashboard"))
            
        except Exception as e:
            flash(f"שגיאה ביצירת המשימה: {str(e)}", "danger")
            db.session.rollback()
    
    return render_template("admin/admin_create_task.html")

@admin_scheduler_bp.route("/edit/<int:task_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_task(task_id):
    """עריכת משימה קיימת"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    if request.method == "POST":
        try:
            # עדכון נתונים
            task.task_name = request.form.get("task_name")
            task.task_type = request.form.get("task_type")
            task.description = request.form.get("description")
            
            # זמן הפעלה
            execution_hour = int(request.form.get("execution_hour", 0))
            execution_minute = int(request.form.get("execution_minute", 0))
            task.execution_time = time(execution_hour, execution_minute)
            
            # סוג תזמון
            task.schedule_type = request.form.get("schedule_type")
            
            # הגדרות התזמון
            schedule_details = {}
            if task.schedule_type == "weekly":
                schedule_details["weekday"] = int(request.form.get("weekday", 0))
            elif task.schedule_type == "monthly":
                schedule_details["day"] = int(request.form.get("monthly_day", 1))
            elif task.schedule_type == "specific_date":
                schedule_details["date"] = request.form.get("specific_date")
            
            task.set_schedule_details(schedule_details)
            task.calculate_next_run()
            
            db.session.commit()
            
            flash(f"המשימה '{task.task_name}' עודכנה בהצלחה!", "success")
            return redirect(url_for("admin_scheduler_bp.scheduler_dashboard"))
            
        except Exception as e:
            flash(f"שגיאה בעדכון המשימה: {str(e)}", "danger")
            db.session.rollback()
    
    return render_template("admin/admin_edit_task.html", task=task)

@admin_scheduler_bp.route("/toggle/<int:task_id>", methods=["POST"])
@login_required
@admin_required
def toggle_task(task_id):
    """הפעלה/כיבוי משימה"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    task.is_active = not task.is_active
    
    if task.is_active:
        task.calculate_next_run()
    else:
        task.next_run = None
    
    db.session.commit()
    
    status = "הופעלה" if task.is_active else "הושבתה"
    flash(f"המשימה '{task.task_name}' {status} בהצלחה!", "success")
    
    return redirect(url_for("admin_scheduler_bp.scheduler_dashboard"))

@admin_scheduler_bp.route("/delete/<int:task_id>", methods=["POST"])
@login_required
@admin_required
def delete_task(task_id):
    """מחיקת משימה"""
    task = ScheduledTask.query.get_or_404(task_id)
    task_name = task.task_name
    
    db.session.delete(task)
    db.session.commit()
    
    flash(f"המשימה '{task_name}' נמחקה בהצלחה!", "success")
    return redirect(url_for("admin_scheduler_bp.scheduler_dashboard"))

@admin_scheduler_bp.route("/run-now/<int:task_id>", methods=["POST"])
@login_required
@admin_required
def run_task_now(task_id):
    """הרצה מיידית של משימה"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    try:
        from app.scheduler import run_scheduled_task
        result = run_scheduled_task(task)
        
        if result.get('success', False):
            flash(f"המשימה '{task.task_name}' רצה בהצלחה!", "success")
        else:
            flash(f"שגיאה בהרצת המשימה: {result.get('error', 'שגיאה לא ידועה')}", "danger")
            
    except Exception as e:
        flash(f"שגיאה בהרצת המשימה: {str(e)}", "danger")
    
    return redirect(url_for("admin_scheduler_bp.scheduler_dashboard"))

@admin_scheduler_bp.route("/logs/<int:task_id>")
@login_required
@admin_required
def task_logs(task_id):
    """הצגת יומן הפעלות של משימה"""
    task = ScheduledTask.query.get_or_404(task_id)
    logs = TaskExecutionLog.query.filter_by(task_id=task_id).order_by(TaskExecutionLog.executed_at.desc()).limit(50).all()
    
    return render_template("admin/admin_task_logs.html", task=task, logs=logs)

@admin_scheduler_bp.route("/api/tasks", methods=["GET"])
@login_required
@admin_required
def api_get_tasks():
    """API לקבלת רשימת המשימות"""
    tasks = ScheduledTask.query.all()
    
    tasks_data = []
    for task in tasks:
        tasks_data.append({
            'id': task.id,
            'name': task.task_name,
            'type': task.task_type,
            'schedule_type': task.schedule_type,
            'execution_time': task.execution_time.strftime('%H:%M'),
            'next_run': task.next_run.isoformat() if task.next_run else None,
            'is_active': task.is_active,
            'last_run': task.last_run.isoformat() if task.last_run else None
        })
    
    return jsonify(tasks_data)

@admin_scheduler_bp.route("/coupon-settings")
@login_required
@admin_required
def coupon_auto_update_settings():
    """מסך הגדרות עדכון אוטומטי לקופונים"""
    # שליפת כל הקופונים
    coupons = Coupon.query.order_by(Coupon.date_added.desc()).all()
    
    # סטטיסטיקות
    total_coupons = len(coupons)
    auto_update_enabled = sum(1 for c in coupons if c.auto_update)
    auto_update_disabled = total_coupons - auto_update_enabled
    
    stats = {
        'total_coupons': total_coupons,
        'auto_update_enabled': auto_update_enabled,
        'auto_update_disabled': auto_update_disabled
    }
    
    return render_template("admin/admin_coupon_auto_update.html", coupons=coupons, stats=stats)

@admin_scheduler_bp.route("/update-coupon-auto-update", methods=["POST"])
@login_required
@admin_required
def update_coupon_auto_update():
    """עדכון הגדרות עדכון אוטומטי לקופון בודד"""
    try:
        coupon_id = request.json.get('coupon_id')
        auto_update = request.json.get('auto_update', False)
        
        coupon = Coupon.query.get_or_404(coupon_id)
        coupon.auto_update = auto_update
        
        db.session.commit()
        
        action = "הופעל" if auto_update else "הושבת"
        return jsonify({
            'success': True,
            'message': f'עדכון אוטומטי {action} עבור קופון {coupon.code}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@admin_scheduler_bp.route("/bulk-update-auto-update", methods=["POST"])
@login_required
@admin_required
def bulk_update_auto_update():
    """עדכון מסיבי של הגדרות עדכון אוטומטי"""
    try:
        action = request.form.get('action')  # 'enable_all' or 'disable_all'
        selected_coupons = request.form.getlist('selected_coupons')
        
        if action == 'enable_all':
            if selected_coupons:
                # עדכון קופונים נבחרים
                Coupon.query.filter(Coupon.id.in_(selected_coupons)).update(
                    {Coupon.auto_update: True}, synchronize_session=False
                )
                count = len(selected_coupons)
                message = f"עדכון אוטומטי הופעל עבור {count} קופונים נבחרים"
            else:
                # עדכון כל הקופונים
                result = Coupon.query.update({Coupon.auto_update: True}, synchronize_session=False)
                message = f"עדכון אוטומטי הופעל עבור כל הקופונים ({result} קופונים)"
                
        elif action == 'disable_all':
            if selected_coupons:
                # עדכון קופונים נבחרים
                Coupon.query.filter(Coupon.id.in_(selected_coupons)).update(
                    {Coupon.auto_update: False}, synchronize_session=False
                )
                count = len(selected_coupons)
                message = f"עדכון אוטומטי הושבת עבור {count} קופונים נבחרים"
            else:
                # עדכון כל הקופונים
                result = Coupon.query.update({Coupon.auto_update: False}, synchronize_session=False)
                message = f"עדכון אוטומטי הושבת עבור כל הקופונים ({result} קופונים)"
        else:
            flash("פעולה לא חוקית", "danger")
            return redirect(url_for("admin_scheduler_bp.coupon_auto_update_settings"))
        
        db.session.commit()
        flash(message, "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"שגיאה בעדכון: {str(e)}", "danger")
    
    return redirect(url_for("admin_scheduler_bp.coupon_auto_update_settings"))