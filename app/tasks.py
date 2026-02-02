"""
Background tasks for coupon updates using Redis Queue (RQ)
"""
import os
import logging
from datetime import datetime
import time
import requests
import zipfile
import json
import pandas as pd
from io import BytesIO
from rq import Queue, Worker
import redis
from datetime import timezone

# Configure Redis connection
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = redis.from_url(redis_url)

# Create queue
task_queue = Queue('coupon_updates', connection=redis_conn)
# ...




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

            logger.debug(f"User updates for email summary: {user_updates}")

            for uid, items in user_updates.items():
                logger.debug(f"Attempting to send summary email for user {uid} with {len(items)} items.")
                try:
                    user = User.query.get(uid)
                    if not user or not user.email:
                        logger.debug(f"Skipping email for user {uid}: user not found or email missing.")
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
                    logger.debug(f"Calling send_email for user {uid} ({user.email}).")
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
    worker = Worker(['coupon_updates'], connection=redis_conn)
    worker.work()



def dispatch_multipass_github_workflow(coupon_codes):
    """
    Dispatch the Multipass GitHub Actions workflow and return quickly.

    Intended for cron/web triggers that only need the workflow to start.
    """
    logger = logging.getLogger("github_updater")

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN not found in environment variables")
        return {"success": False, "error": "Missing GITHUB_TOKEN"}

    repo_owner = os.getenv("MULTIPASS_GH_OWNER", "itayk93")
    repo_name = os.getenv("MULTIPASS_GH_REPO", "scrape_multipass")
    workflow_id = os.getenv("MULTIPASS_GH_WORKFLOW", "scrape.yml")
    workflow_ref = os.getenv("MULTIPASS_GH_REF", "main")
    input_key = os.getenv("MULTIPASS_GH_INPUT_KEY", "card_number")
    input_separator = os.getenv("MULTIPASS_GH_INPUT_SEPARATOR", ",")

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    safe_codes = [str(c).strip() for c in (coupon_codes or []) if str(c).strip()]
    if not safe_codes:
        return {"success": False, "error": "No coupon codes provided"}

    trigger_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        f"/actions/workflows/{workflow_id}/dispatches"
    )
    card_numbers_str = input_separator.join(safe_codes)
    payload = {
        "ref": workflow_ref,
        "inputs": {
            input_key: card_numbers_str,
        },
    }

    logger.info(
        "Dispatching GitHub workflow %s/%s (%s) ref=%s input_key=%s coupons=%d",
        repo_owner,
        repo_name,
        workflow_id,
        workflow_ref,
        input_key,
        len(safe_codes),
    )

    resp = requests.post(trigger_url, headers=headers, json=payload, timeout=20)
    if resp.status_code != 204:
        logger.error("Failed to dispatch workflow (status=%s): %s", resp.status_code, resp.text)
        return {
            "success": False,
            "error": "GitHub workflow dispatch failed",
            "status_code": resp.status_code,
            "response": resp.text,
        }

    # Best-effort: fetch the newest workflow_dispatch run id/url for this workflow.
    run_id = None
    run_url = None
    try:
        time.sleep(2)
        runs_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}"
            f"/actions/workflows/{workflow_id}/runs?event=workflow_dispatch&per_page=1"
        )
        r = requests.get(runs_url, headers=headers, timeout=20)
        if r.status_code == 200:
            runs = r.json().get("workflow_runs", [])
            if runs:
                run_id = runs[0].get("id")
                run_url = runs[0].get("html_url")
    except Exception as exc:
        logger.warning("Could not fetch dispatched run info: %s", exc)

    return {
        "success": True,
        "workflow": workflow_id,
        "ref": workflow_ref,
        "run_id": run_id,
        "run_url": run_url,
    }


def trigger_multipass_github_action(coupon_codes):
    """
    Background task to trigger GitHub Action for Multipass scraping.
    
    1. Triggers workflow_dispatch
    2. Polls for completion
    3. Downloads artifact
    4. Updates DB
    """
    from app import create_app
    from app.models import Coupon, CouponUsage
    from app.helpers import process_multipass_json, update_coupon_status
    from app.extensions import db
    
    app = create_app()
    
    with app.app_context():
        logger = logging.getLogger('github_updater')
        
        repo_owner = os.getenv("MULTIPASS_GH_OWNER", "itayk93")
        repo_name = os.getenv("MULTIPASS_GH_REPO", "scrape_multipass")
        workflow_id = os.getenv("MULTIPASS_GH_WORKFLOW", "scrape.yml")
        workflow_ref = os.getenv("MULTIPASS_GH_REF", "main")
        input_key = os.getenv("MULTIPASS_GH_INPUT_KEY", "card_number")
        input_separator = os.getenv("MULTIPASS_GH_INPUT_SEPARATOR", ",")
        
        # 1. Trigger Workflow
        dispatch_result = dispatch_multipass_github_workflow(coupon_codes)
        if not dispatch_result.get("success"):
            return dispatch_result

        github_token = os.getenv("GITHUB_TOKEN")
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
            
        # 2. Wait for the run to start and complete
        logger.info("Workflow triggered. Waiting for run to appear...")
        time.sleep(10) 
        
        runs_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}"
            f"/actions/workflows/{workflow_id}/runs?event=workflow_dispatch&per_page=1"
        )
        run_id = None
        
        # Poll for run ID
        for i in range(5):
            r = requests.get(runs_url, headers=headers)
            if r.status_code == 200:
                runs = r.json().get("workflow_runs", [])
                if runs:
                    latest_run = runs[0]
                    run_id = latest_run["id"]
                    logger.info(f"Found Run ID: {run_id} (Status: {latest_run['status']})")
                    break
            time.sleep(2)
            
        if not run_id:
            logger.error("Could not find the GitHub Action run.")
            return {'success': False, 'error': "Could not locate GitHub Action run"}
            
        # 3. Poll for completion
        status = "queued"
        conclusion = None
        
        max_retries = 180 # 30 minutes (180 * 10s) 
        for i in range(max_retries):
            run_detail_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs/{run_id}"
            r = requests.get(run_detail_url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                status = data["status"]
                conclusion = data["conclusion"]
                logger.info(f"Run {run_id} status: {status}")
                
                if status == "completed":
                    break
            time.sleep(10)
            
        if status != "completed":
            logger.error(f"Run {run_id} timed out or did not complete.")
            return {'success': False, 'error': "GitHub Action timed out"}
            
        if conclusion != "success":
            logger.error(f"Run {run_id} failed with conclusion: {conclusion}")
            return {'success': False, 'error': f"GitHub Action failed: {conclusion}"}
            
        # 4. Download Artifacts
        artifacts_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs/{run_id}/artifacts"
        r = requests.get(artifacts_url, headers=headers)
        
        transaction_data_map = {}
        
        if r.status_code == 200:
            artifacts = r.json().get("artifacts", [])
            target_artifact = next((a for a in artifacts if a["name"] == "transactions-json"), None)
            
            if target_artifact:
                download_url = target_artifact["archive_download_url"]
                logger.info(f"Downloading artifact from {download_url}")
                
                zip_resp = requests.get(download_url, headers=headers)
                
                if zip_resp.status_code == 200:
                    with zipfile.ZipFile(BytesIO(zip_resp.content)) as z:
                        logger.info(f"Zip file content: {z.namelist()}")
                        
                        # STRICT: Look for exact 'transactions.json'
                        json_filename = "transactions.json"
                        if json_filename not in z.namelist():
                             # Fallback: look for any json
                             json_filename = next((name for name in z.namelist() if name.endswith('.json')), None)
                        
                        if json_filename:
                            logger.info(f"Processing JSON file: {json_filename}")
                            with z.open(json_filename) as f:
                                all_data = json.load(f)
                                logger.info(f"Loaded {len(all_data)} items from JSON")
                                if len(all_data) > 0:
                                    logger.info(f"Sample item keys: {list(all_data[0].keys())}")
                                    logger.info(f"Sample item content: {json.dumps(all_data[0], ensure_ascii=False)}")
                                
                                for item in all_data:
                                    c_num = item.get("card_number")
                                    if c_num:
                                        ts = item.get("transactions", [])
                                        transaction_data_map[c_num] = ts
                                        logger.info(f"Card {c_num}: Found {len(ts)} transactions in JSON")
                        else:
                            logger.warning("No JSON file found in artifact zip")
                else:
                    logger.error(f"Failed to download artifact: {zip_resp.status_code}")
            else:
                logger.error("Artifact 'transactions-json' not found")
        else:
            logger.error(f"Failed to list artifacts: {r.status_code}")
            
        # 5. Update Database
        updated_count = 0
        failed_count = 0
        results = {
            'successful': [],
            'failed': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        # Pre-fetch coupons to handle EncryptedString lookup issue
        # We cannot use filter_by(code=code) because code is encrypted in DB.
        potential_coupons = Coupon.query.filter(
            Coupon.auto_download_details == 'Multipass',
            Coupon.status == 'פעיל'
        ).all()
        
        # Create a map of decrypted code -> coupon object
        # Accessing c.code triggers decryption
        db_coupon_map = {c.code: c for c in potential_coupons}

        for code, transactions in transaction_data_map.items():
            # coupon = Coupon.query.filter_by(code=code).first() # This fails due to encryption
            coupon = db_coupon_map.get(code)
            
            if not coupon:
                # Try fuzzy matching or stripping whitespace if direct match fails
                # e.g. " 123 " vs "123"
                normalized_code = code.strip()
                coupon = db_coupon_map.get(normalized_code)
                
            if not coupon:
                logger.warning(f"Coupon with code {code} not found in DB map during update.")
                continue
                
            logger.info(f"Updating coupon {code} with {len(transactions)} transactions")
            
            old_usage = coupon.used_value or 0
            
            try:
                from app.helpers import process_multipass_json
                df_new = process_multipass_json(coupon, transactions)
                
                if df_new is not None:
                     updated_count += 1
                     new_usage_sum = float(df_new['usage_amount'].sum()) if not df_new.empty else 0.0
                     
                     if new_usage_sum > 0:
                        usage_record = CouponUsage(
                            coupon_id=coupon.id,
                            used_amount=new_usage_sum,
                            timestamp=datetime.now(timezone.utc),
                            action="Github Action Update",
                            details="עדכון אוטומטי via GitHub Action",
                        )
                        db.session.add(usage_record)
                        db.session.commit()
                        
                     # Capture result for email
                     new_total_usage = coupon.used_value or 0
                     coupon_value = float(coupon.value or 0)
                     
                     results['successful'].append({
                        'coupon_code': coupon.code,
                        'company': coupon.company,
                        'old_usage': float(old_usage),
                        'new_usage': float(new_total_usage),
                        'coupon_value': coupon_value,
                        'remaining_value': max(coupon_value - new_total_usage, 0),
                        'user_id': coupon.user_id
                     })
                     
                else:
                    failed_count += 1
                    results['failed'].append({'coupon_code': code, 'error': 'Failed to process JSON'})

            except Exception as e:
                logger.error(f"Error updating coupon {code}: {e}")
                failed_count += 1
                db.session.rollback()
                results['failed'].append({'coupon_code': code, 'error': str(e)})

        results['end_time'] = datetime.now().isoformat()
        results['success_count'] = updated_count
        results['failure_count'] = failed_count
        
        # Send per-user email summaries
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
                old_u = item.get('old_usage', 0)
                new_u = item.get('new_usage', 0)
                delta = new_u - old_u
                
                # Only report if there is a change
                if delta <= 0:
                    continue
                    
                if user_id not in user_updates:
                    user_updates[user_id] = []
                    
                item['delta'] = delta
                user_updates[user_id].append(item)

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
                        success_count=len(items), # Count only relevant items for this user
                        failure_count=0, # We don't report failures to user in this context usually
                        started=started,
                        ended=ended,
                    )
                    subject = 'סיכום עדכון קופונים (GitHub Multipass)'
                    send_email(
                        sender_email=SENDER_EMAIL,
                        sender_name=SENDER_NAME,
                        recipient_email=user.email,
                        recipient_name=user.first_name,
                        subject=subject,
                        html_content=html,
                    )
                    logger.info(f"Summary email sent to user {uid}")
                except Exception as e:
                    logger.error(f"Failed sending summary email to user {uid}: {e}")
                    
        except Exception as e:
            logger.error(f"Summary email dispatch failed: {e}")
                
        return results


if __name__ == '__main__':
    # Start worker if this file is run directly
    start_worker()
