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

def update_coupon_task(coupon_id, max_retries=3):
    """
    Background task to update a single coupon
    """
    from app import create_app
    from app.models import Coupon, CouponUsage
    from app.helpers import get_coupon_data_with_retry, update_coupon_status
    from app.extensions import db
    from datetime import timezone
    
    app = create_app()
    
    with app.app_context():
        logger = logging.getLogger('multipass_updater')
        
        try:
            coupon = Coupon.query.get(coupon_id)
            if not coupon:
                logger.error(f"Coupon with ID {coupon_id} not found")
                return {'success': False, 'error': f'Coupon {coupon_id} not found'}
            
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
                return {
                    'success': True, 
                    'coupon_code': coupon.code,
                    'company': coupon.company,
                    'old_usage': old_usage,
                    'new_usage': total_usage
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
            return {
                'success': False, 
                'error': str(e),
                'coupon_id': coupon_id
            }


def update_multiple_coupons_task(coupon_ids, max_retries=3):
    """
    Background task to update multiple coupons
    """
    from app import create_app
    
    app = create_app()
    
    with app.app_context():
        logger = logging.getLogger('multipass_updater')
        logger.info(f"Starting batch update for {len(coupon_ids)} coupons")
        
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


def enqueue_multiple_coupon_updates(coupon_ids, max_retries=3):
    """
    Enqueue multiple coupon updates as a single batch job
    """
    job = task_queue.enqueue(
        update_multiple_coupons_task,
        coupon_ids,
        max_retries,
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