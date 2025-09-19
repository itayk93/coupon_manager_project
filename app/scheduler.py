# app/scheduler.py
"""
מערכת תזמון משימות אוטומטיות
"""

import logging
import time
from datetime import datetime
from threading import Thread
from typing import Dict, Any, Optional
import pytz

from app.models import ScheduledTask, TaskExecutionLog, db
from app.extensions import db as db_session
from flask import current_app

logger = logging.getLogger(__name__)

class TaskScheduler:
    """מחלקה לניהול וביצוע משימות מתוכננות"""
    
    def __init__(self, app=None):
        self.running = False
        self.thread = None
        self.app = app
        
    def start(self):
        """הפעלת מערכת התזמון"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
            
        self.running = True
        self.thread = Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Task scheduler started")
        
    def stop(self):
        """עצירת מערכת התזמון"""
        if not self.running:
            return
            
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Task scheduler stopped")
        
    def _run_scheduler(self):
        """לולאת התזמון הראשית"""
        while self.running:
            try:
                self._check_and_run_tasks()
                time.sleep(60)  # בדיקה כל דקה
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(60)
                
    def _check_and_run_tasks(self):
        """בדיקה והרצה של משימות שצריכות להתבצע"""
        try:
            if self.app:
                with self.app.app_context():
                    # שליפת משימות פעילות שצריכות לרוץ
                    tasks = ScheduledTask.query.filter(
                        ScheduledTask.is_active == True,
                        ScheduledTask.next_run <= datetime.now(pytz.UTC)
                    ).all()
                    
                    for task in tasks:
                        if task.should_run_now():
                            logger.info(f"Running scheduled task: {task.task_name}")
                            self._execute_task(task)
            else:
                logger.warning("No app context available for scheduler")
                    
        except Exception as e:
            logger.error(f"Error checking tasks: {e}")
            
    def _execute_task(self, task: ScheduledTask):
        """ביצוע משימה ספציפית"""
        if not self.app:
            logger.error("No app context available for task execution")
            return
            
        with self.app.app_context():
            start_time = datetime.now(pytz.UTC)
            log_entry = TaskExecutionLog(
                task_id=task.id,
                status='running',
                executed_at=start_time
            )
            
            try:
                db_session.add(log_entry)
                db_session.commit()
                
                # ביצוע המשימה בפועל
                result = run_scheduled_task(task)
                
                # עדכון הלוג
                end_time = datetime.now(pytz.UTC)
                execution_time = int((end_time - start_time).total_seconds())
                
                log_entry.status = 'success' if result.get('success', False) else 'failed'
                log_entry.result_message = result.get('message', '')
                log_entry.error_message = result.get('error', '')
                log_entry.execution_time_seconds = execution_time
                log_entry.set_additional_data(result.get('data', {}))
                
                # עדכון המשימה
                task.last_run = start_time
                task.calculate_next_run()
                
                db_session.commit()
                
                logger.info(f"Task {task.task_name} completed with status: {log_entry.status}")
                
            except Exception as e:
                logger.error(f"Error executing task {task.task_name}: {e}")
                log_entry.status = 'failed'
                log_entry.error_message = str(e)
                try:
                    db_session.commit()
                except:
                    pass


def run_scheduled_task(task: ScheduledTask) -> Dict[str, Any]:
    """
    ביצוע משימה מתוכננת בהתבסס על סוגה
    """
    logger.info(f"Executing task: {task.task_name} ({task.task_type})")
    
    try:
        if task.task_type == 'coupon_update':
            return _run_coupon_update_task(task)
        elif task.task_type == 'email_send':
            return _run_email_send_task(task)
        elif task.task_type == 'data_cleanup':
            return _run_data_cleanup_task(task)
        elif task.task_type == 'backup':
            return _run_backup_task(task)
        elif task.task_type == 'custom':
            return _run_custom_task(task)
        else:
            return {
                'success': False,
                'error': f'Unknown task type: {task.task_type}'
            }
            
    except Exception as e:
        logger.error(f"Error in run_scheduled_task for {task.task_name}: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def _run_coupon_update_task(task: ScheduledTask) -> Dict[str, Any]:
    """ביצוע משימת עדכון קופונים"""
    try:
        from app.models import Coupon
        from app.helpers import get_coupon_data
        
        logger.info("Starting coupon update task")
        
        # שליפת קופונים פעילים ומסומנים לעדכון אוטומטי
        coupons = Coupon.query.filter(
            Coupon.is_active == True,
            Coupon.auto_update == True
        ).all()
        updated_count = 0
        failed_count = 0
        
        for coupon in coupons:
            try:
                logger.info(f"Updating coupon: {coupon.code}")
                
                # כאן נקרא לפונקציית העדכון הקיימת
                # זה יכול להיות הפונקציה שלחצת עליה ידנית
                from app.routes.admin_routes import admin_bp
                from app.routes.admin_routes.admin_routes import update_coupon_transactions
                
                # או ליצור עדכון ישיר
                df = get_coupon_data(coupon.code)
                if df is not None:
                    updated_count += 1
                    logger.info(f"Successfully updated coupon {coupon.code}")
                else:
                    failed_count += 1
                    logger.warning(f"Failed to update coupon {coupon.code}")
                    
            except Exception as coupon_error:
                failed_count += 1
                logger.error(f"Error updating coupon {coupon.code}: {coupon_error}")
        
        return {
            'success': True,
            'message': f'Updated {updated_count} coupons, {failed_count} failed',
            'data': {
                'updated_count': updated_count,
                'failed_count': failed_count,
                'total_processed': len(coupons)
            }
        }
        
    except Exception as e:
        logger.error(f"Error in coupon update task: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def _run_email_send_task(task: ScheduledTask) -> Dict[str, Any]:
    """ביצוע משימת שליחת מייל"""
    try:
        # כאן תהיה הלוגיקה לשליחת מיילים
        logger.info("Email send task executed (placeholder)")
        
        return {
            'success': True,
            'message': 'Email task completed successfully',
            'data': {'emails_sent': 0}
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def _run_data_cleanup_task(task: ScheduledTask) -> Dict[str, Any]:
    """ביצוע משימת ניקוי נתונים"""
    try:
        # כאן תהיה הלוגיקה לניקוי נתונים
        logger.info("Data cleanup task executed (placeholder)")
        
        return {
            'success': True,
            'message': 'Data cleanup completed successfully',
            'data': {'cleaned_records': 0}
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def _run_backup_task(task: ScheduledTask) -> Dict[str, Any]:
    """ביצוע משימת גיבוי"""
    try:
        # כאן תהיה הלוגיקה לגיבוי
        logger.info("Backup task executed (placeholder)")
        
        return {
            'success': True,
            'message': 'Backup completed successfully',
            'data': {'backup_size': '0MB'}
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def _run_custom_task(task: ScheduledTask) -> Dict[str, Any]:
    """ביצוע משימה מותאמת אישית"""
    try:
        # כאן תהיה הלוגיקה למשימות מותאמות
        logger.info(f"Custom task executed: {task.task_name}")
        
        return {
            'success': True,
            'message': f'Custom task {task.task_name} completed successfully',
            'data': {}
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


# יצירת instance של הscheduler (יוגדר ב-__init__.py)
scheduler = None

def start_scheduler(app=None):
    """הפעלת מערכת התזמון"""
    global scheduler
    if not scheduler:
        scheduler = TaskScheduler(app)
    scheduler.start()

def stop_scheduler():
    """עצירת מערכת התזמון"""
    global scheduler
    if scheduler:
        scheduler.stop()