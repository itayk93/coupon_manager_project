#!/usr/bin/env python3
"""
Daily expiration reminders script for cron job
This script sends email reminders for coupons expiring in 30, 7, and 1 days
"""

import os
import sys
import logging
import requests
from datetime import datetime

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def setup_logging():
    """Setup logging for the expiration reminder script"""
    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/expiration_reminders.log'),
            logging.StreamHandler()
        ]
    )

def send_expiration_reminders():
    """Send expiration reminders using the Flask app endpoint"""
    setup_logging()
    logger = logging.getLogger('expiration_reminders')
    
    try:
        logger.info("=== Starting Expiration Reminders ===")
        
        # Import Flask app to get the base URL
        from app import create_app
        
        app = create_app()
        
        with app.app_context():
            # Use local endpoint since we're running on the same server
            endpoint_url = "http://localhost:5000/admin/scheduled-emails/api/cron/send-expiration-reminders"
            
            # Get the API token from app config
            api_token = app.config.get('CRON_API_TOKEN')
            if not api_token:
                logger.error("CRON_API_TOKEN not found in configuration")
                sys.exit(1)
            
            # Prepare headers with authorization token
            headers = {
                'Authorization': f'Bearer {api_token}',
                'Content-Type': 'application/json'
            }
            
            # Make POST request to the endpoint
            response = requests.post(endpoint_url, headers=headers, timeout=300)
            
            if response.status_code == 200:
                result = response.json()
                logger.info("=== Expiration Reminders Completed Successfully ===")
                logger.info(f"Status: {result.get('status', 'unknown')}")
                logger.info(f"Message: {result.get('message', 'No message')}")
                
                if 'data' in result:
                    data = result['data']
                    logger.info(f"Sent reminders: {data.get('sent_count', 0)}")
                    logger.info(f"Failed reminders: {data.get('failed_count', 0)}")
                    
                    if data.get('sent_reminders'):
                        logger.info("Successfully sent reminders:")
                        for reminder in data['sent_reminders']:
                            logger.info(f"  - {reminder['type']} reminder to {reminder['user_email']} for {reminder['company']} ({reminder['code']})")
                    
                    if data.get('failed_reminders'):
                        logger.warning("Failed reminders:")
                        for reminder in data['failed_reminders']:
                            logger.warning(f"  - {reminder['type']} reminder to {reminder['user_email']}: {reminder['error']}")
                            
            else:
                logger.error(f"Failed to send reminders. Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
                sys.exit(1)
                
    except Exception as e:
        logger.error(f"Fatal error in expiration reminders: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    send_expiration_reminders()