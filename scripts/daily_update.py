#!/usr/bin/env python3
"""
Daily automatic coupon update script for Render cron job
This script runs daily to update all active coupons automatically
"""

import os
import sys
import logging
from datetime import datetime

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def setup_logging():
    """Setup logging for the daily update script"""
    # Create logs directory if it doesn't exist
    import os
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/daily_update.log'),
            logging.StreamHandler()
        ]
    )

def main():
    """Main function to run daily coupon updates"""
    setup_logging()
    logger = logging.getLogger('daily_update')
    
    try:
        logger.info("=== Starting Daily Coupon Update ===")
        
        # Import Flask app and models
        from app import create_app
        from app.models import Coupon
        from app.tasks import enqueue_multiple_coupon_updates
        
        app = create_app()
        
        with app.app_context():
            # Get all active coupons that can be updated automatically
            updatable_coupons = Coupon.query.filter(
                Coupon.status == "פעיל",
                Coupon.is_one_time == False,
                Coupon.auto_download_details.isnot(None)
            ).all()
            
            if not updatable_coupons:
                logger.info("No updatable coupons found")
                return
            
            logger.info(f"Found {len(updatable_coupons)} coupons to update")
            
            # Log coupon details
            for coupon in updatable_coupons:
                logger.info(f"  - {coupon.code} ({coupon.company}) - {coupon.auto_download_details}")
            
            # Use the new endpoint logic directly
            try:
                from app.tasks import enqueue_multiple_coupon_updates
                
                coupon_ids = [c.id for c in updatable_coupons]
                job = enqueue_multiple_coupon_updates(coupon_ids, max_retries=3)
                logger.info(f"Enqueued batch update job: {job.id}")
            except ImportError:
                logger.warning("Redis/RQ not available, using synchronous processing")
                # Direct synchronous processing fallback
                from app.helpers import get_coupon_data_with_retry, update_coupon_status
                from app.models import CouponUsage
                from app.extensions import db
                from datetime import timezone
                
                updated_count = 0
                failed_count = 0
                
                for cpn in updatable_coupons:
                    try:
                        df = get_coupon_data_with_retry(cpn, max_retries=3)  
                        if df is not None:
                            total_usage = float(df["usage_amount"].sum())
                            cpn.used_value = total_usage
                            update_coupon_status(cpn)

                            usage = CouponUsage(
                                coupon_id=cpn.id,
                                used_amount=total_usage,
                                timestamp=datetime.now(timezone.utc),
                                action="עדכון יומי",
                                details="עדכון יומי אוטומטי",
                            )
                            db.session.add(usage)
                            updated_count += 1
                            logger.info(f"✅ Updated coupon {cpn.code}: {total_usage}")
                        else:
                            failed_count += 1
                            logger.warning(f"❌ Failed to update coupon {cpn.code}: No data")
                    except Exception as e:
                        failed_count += 1
                        logger.error(f"💥 Error updating coupon {cpn.code}: {e}")
                        db.session.rollback()
                
                try:
                    db.session.commit()
                    logger.info(f"=== Daily Update Completed ===")
                    logger.info(f"Updated: {updated_count}, Failed: {failed_count}")
                    return
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Database commit failed: {e}")
                    raise e
            
            # Wait for job completion (with timeout)
            import time
            timeout = 1800  # 30 minutes
            start_time = time.time()
            
            while not job.is_finished and not job.is_failed:
                time.sleep(30)  # Check every 30 seconds
                job.refresh()
                
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.error(f"Job timed out after {timeout} seconds")
                    break
                    
                logger.info(f"Job status: {job.get_status()} (elapsed: {elapsed:.1f}s)")
            
            # Report results
            if job.is_finished:
                result = job.result
                logger.info("=== Daily Update Completed Successfully ===")
                logger.info(f"Total coupons: {result['total']}")
                logger.info(f"Successful: {result['success_count']}")
                logger.info(f"Failed: {result['failure_count']}")
                
                if result['failed']:
                    logger.warning("Failed coupons:")
                    for failed in result['failed']:
                        logger.warning(f"  - {failed.get('coupon_code', 'Unknown')}: {failed['error']}")
                        
            elif job.is_failed:
                logger.error("=== Daily Update Failed ===")
                logger.error(f"Job failed with error: {job.exc_info}")
            else:
                logger.warning("=== Daily Update Timed Out ===")
                logger.warning("Job did not complete within timeout period")
                
    except Exception as e:
        logger.error(f"Fatal error in daily update: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()