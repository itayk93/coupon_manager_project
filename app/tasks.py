"""
Background tasks for coupon updates using Redis Queue (RQ)
"""
import os
import logging
from datetime import datetime
from rq import Queue, Worker, Connection
import redis

# Configure Redis connection
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = redis.from_url(redis_url)

# Create queue
task_queue = Queue('coupon_updates', connection=redis_conn)


def enqueue_coupon_status_sync(coupon_ids):
    """Enqueue a background job to reconcile coupon statuses."""
    if not coupon_ids:
        return None

    # Ensure we don't enqueue duplicate IDs in a single job
    unique_ids = list(dict.fromkeys(coupon_ids))
    return task_queue.enqueue(sync_coupon_statuses_task, unique_ids, job_timeout=180)


def sync_coupon_statuses_task(coupon_ids):
    """Background task to update coupon statuses without blocking requests."""
    from app import create_app
    from app.extensions import db
    from app.helpers import update_coupon_status
    from app.models import Coupon

    app = create_app()

    with app.app_context():
        updated = 0
        try:
            coupons = Coupon.query.filter(Coupon.id.in_(coupon_ids)).all()
            for coupon in coupons:
                previous_status = coupon.status
                new_status = update_coupon_status(coupon)
                if new_status != previous_status:
                    updated += 1

            if updated:
                db.session.commit()
            else:
                db.session.rollback()

            return {
                'success': True,
                'updated': updated,
                'total': len(coupons)
            }
        except Exception as exc:
            db.session.rollback()
            return {
                'success': False,
                'error': str(exc),
                'total': 0
            }

def update_coupon_task(coupon_id, max_retries=3):
    """
    Background task to update a single coupon
    """
    from app import create_app
    from app.models import Coupon, CouponUsage
    from app.helpers import get_coupon_data_with_retry, update_coupon_status
    from app.extensions import db
    from datetime import datetime, timezone
    
    app = create_app()
    
    with app.app_context():
        logger = logging.getLogger('multipass_updater')
        
        coupon = Coupon.query.get(coupon_id)
        if not coupon:
            logger.error(f"Coupon with ID {coupon_id} not found")
            return {'success': False, 'error': f'Coupon {coupon_id} not found'}

        try:
            logger.info(f"Starting background update for coupon {coupon.code}")
            
            # Get coupon data with retry mechanism
            df = get_coupon_data_with_retry(coupon, max_retries=max_retries)
            
            if df is not None:
                total_usage = float(df["usage_amount"].sum())
                old_usage = coupon.used_value or 0
                
                # Update coupon
                coupon.used_value = total_usage
                update_coupon_status(coupon)
                
                # Log usage
                usage = CouponUsage(
                    coupon_id=coupon.id,
                    used_amount=total_usage,
                    timestamp=datetime.now(timezone.utc),
                    action="עדכון אוטומטי",
                    details=f"עדכון רקע - שינוי מ-{old_usage} ל-{total_usage}",
                )
                db.session.add(usage)
                db.session.commit()
                
                logger.info(f"✅ Background update completed for coupon {coupon.code}")
                coupon_value = float(coupon.value or 0)
                return {
                    'success': True,
                    'coupon_code': coupon.code,
                    'company': coupon.company,
                    'old_usage': old_usage,
                    'new_usage': total_usage,
                    'user_id': coupon.user_id,
                    'coupon_value': coupon_value,
                    'remaining_value': max(coupon_value - total_usage, 0),
                }
            else:
                logger.error(f"❌ Failed to get data for coupon {coupon.code}")
                return {
                    'success': False, 
                    'error': f'No data returned for coupon {coupon.code}',
                    'coupon_code': coupon.code,
                    'company': coupon.company
                }
                
        except Exception as e:
            logger.error(f"💥 Exception in background task for coupon {coupon_id}: {str(e)}")
            db.session.rollback()
            return {
                'success': False, 
                'error': str(e),
                'coupon_id': coupon_id
            }
        finally:
            try:
                if coupon:
                    coupon.last_scraped = datetime.now(timezone.utc)
                    db.session.commit()
                    logger.info(f"Updated last_scraped for coupon {coupon.id}")
            except Exception as e:
                logger.error(f"Failed to update last_scraped for coupon {coupon_id}: {e}")
                db.session.rollback()


def update_multiple_coupons_task(coupon_ids, max_retries=3, run_id=None):
    """
    Background task to update multiple coupons
    """
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        logger = logging.getLogger('multipass_updater')
        logger.info(f"Starting batch update for {len(coupon_ids)} coupons")
        # If we have a run_id, mark the run as running now
        run = None
        if run_id is not None:
            try:
                from app.models import AutoUpdateRun, db as _db
                from datetime import datetime as _dt, timezone as _tz
                run = AutoUpdateRun.query.get(run_id)
                if run:
                    run.status = 'running'
                    # If not started, set started_at
                    if not run.started_at:
                        run.started_at = _dt.now(_tz.utc)
                    _db.session.commit()
            except Exception as e:
                logger.error(f"Failed to mark AutoUpdateRun {run_id} as running: {e}")
        
        results = {
            'total': len(coupon_ids),
            'successful': [],
            'failed': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        for i, coupon_id in enumerate(coupon_ids):
            logger.info(f"Processing coupon {i+1}/{len(coupon_ids)} (ID: {coupon_id})")
            
            try:
                result = update_coupon_task(coupon_id, max_retries)
                
                if result['success']:
                    results['successful'].append(result)
                    logger.info(f"✅ Coupon {result['coupon_code']} updated successfully")
                else:
                    results['failed'].append(result)
                    logger.error(f"❌ Failed to update coupon {result.get('coupon_code', coupon_id)}: {result['error']}")
                    
            except Exception as e:
                error_result = {
                    'success': False,
                    'error': str(e),
                    'coupon_id': coupon_id
                }
                results['failed'].append(error_result)
                logger.error(f"💥 Exception processing coupon {coupon_id}: {str(e)}")
        
        results['end_time'] = datetime.now().isoformat()
        results['success_count'] = len(results['successful'])
        results['failure_count'] = len(results['failed'])

        logger.info(f"Batch update completed: {results['success_count']} successful, {results['failure_count']} failed")

        # Update run record (if provided)
        if run_id is not None:
            try:
                from app.models import AutoUpdateRun, db as _db
                run = AutoUpdateRun.query.get(run_id)
                if run:
                    run.finish(
                        success=True,
                        updated=results['success_count'],
                        failed=results['failure_count'],
                        skipped=0,
                        message='Background batch update completed'
                    )
                    _db.session.commit()
            except Exception as e:
                logger.error(f"Failed to update AutoUpdateRun {run_id}: {e}")

        # Send per-user email summaries for coupons that had increased usage
        try:
            from flask import render_template
            from app.models import User
            from app.helpers import send_email, SENDER_EMAIL, SENDER_NAME

            # Group successful updates by user and filter only positive deltas
            user_updates = {}
            for item in results['successful']:
                user_id = item.get('user_id')
                if user_id is None:
                    continue
                old_u = float(item.get('old_usage', 0) or 0)
                new_u = float(item.get('new_usage', 0) or 0)
                delta = new_u - old_u
                if delta <= 0:
                    continue
                coupon_value = float(item.get('coupon_value', 0) or 0)
                remaining_value = float(item.get('remaining_value', 0) or 0)
                if coupon_value:
                    remaining_value = max(coupon_value - new_u, 0)
                if user_id not in user_updates:
                    user_updates[user_id] = []
                user_updates[user_id].append({
                    'coupon_code': item.get('coupon_code'),
                    'company': item.get('company'),
                    'old_usage': old_u,
                    'new_usage': new_u,
                    'delta': delta,
                    'remaining_value': remaining_value,
                    'coupon_value': coupon_value,
                })

            started = results.get('start_time')
            ended = results.get('end_time')

            for uid, items in user_updates.items():
                try:
                    user = User.query.get(uid)
                    if not user or not user.email:
                        continue
                    html = render_template(
                        'emails/coupon_updates_summary.html',
                        user=user,
                        items=items,
                        success_count=results['success_count'],
                        failure_count=results['failure_count'],
                        started=started,
                        ended=ended,
                    )
                    subject = 'סיכום עדכון קופונים אוטומטי'
                    send_email(
                        sender_email=SENDER_EMAIL,
                        sender_name=SENDER_NAME,
                        recipient_email=user.email,
                        recipient_name=user.first_name,
                        subject=subject,
                        html_content=html,
                    )
                    logger.info(f"Summary email sent to user {uid} ({user.email}) with {len(items)} items")
                except Exception as e:
                    logger.error(f"Failed sending summary email to user {uid}: {e}")
        except Exception as e:
            logger.error(f"Summary email dispatch failed: {e}")

        return results


def enqueue_coupon_update(coupon_id, max_retries=3):
    """
    Enqueue a single coupon update task
    """
    job = task_queue.enqueue(
        update_coupon_task,
        coupon_id,
        max_retries,
        job_timeout='10m'  # 10 minutes timeout
    )
    return job


def enqueue_multiple_coupon_updates(coupon_ids, max_retries=3, run_id=None):
    """
    Enqueue multiple coupon updates as a single batch job
    """
    if run_id is None:
        job = task_queue.enqueue(
            update_multiple_coupons_task,
            coupon_ids,
            max_retries,
            job_timeout='30m'  # 30 minutes timeout for batch
        )
    else:
        job = task_queue.enqueue(
            update_multiple_coupons_task,
            coupon_ids,
            max_retries,
            run_id,
            job_timeout='30m'  # 30 minutes timeout for batch
        )
    return job


def get_job_status(job_id):
    """
    Get the status of a background job
    """
    from rq.job import Job
    
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        
        status = {
            'id': job.id,
            'status': job.get_status(),
            'result': job.result,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'ended_at': job.ended_at.isoformat() if job.ended_at else None,
            'meta': job.meta
        }
        
        if job.is_failed:
            status['error'] = str(job.exc_info)
            
        return status
        
    except Exception as e:
        return {
            'id': job_id,
            'status': 'not_found',
            'error': str(e)
        }


def start_worker():
    """
    Start an RQ worker for processing background tasks
    Use this for development or in a separate worker process
    """
    with Connection(redis_conn):
        worker = Worker(['coupon_updates'])
        worker.work()


if __name__ == '__main__':
    # Start worker if this file is run directly
    start_worker()
