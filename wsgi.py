# wsgi.py
import os
import sys
import logging
import multiprocessing
from app import create_app
from telegram_bot import run_bot

def setup_production_logging():
    """
    Setup logging configuration that works in both development and production environments.
    This ensures telegram bot logs are visible in production deployments.
    """
    # Force unbuffered output for production environments
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    
    # Clear any existing handlers to avoid conflicts
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Create console handler with production-friendly settings
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Create formatter with timestamp and clear message format
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    # Silence noisy third-party loggers but keep our app logs
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('apscheduler.scheduler').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram.ext.Application').setLevel(logging.WARNING)
    logging.getLogger('fuzzywuzzy').setLevel(logging.ERROR)
    
    # Ensure our main loggers stay visible
    logging.getLogger('__main__').setLevel(logging.INFO)
    logging.getLogger('telegram_bot').setLevel(logging.INFO)
    logging.getLogger('app').setLevel(logging.INFO)
    
    # Test log to verify configuration works
    logging.info("=== Logging configured for production deployment ===")

# Initialize logging before anything else
setup_production_logging()

# Create logger for this module
logger = logging.getLogger(__name__)

# Create Flask application
app = create_app()

def start_telegram_bot():
    """
    Start Telegram bot in a separate process.
    This function runs in a daemon process to handle bot operations.
    """
    try:
        # Log with explicit flush to ensure visibility in production
        logger.info("Starting Telegram bot in separate process...")
        print("Starting Telegram bot in separate process...", flush=True)  # Backup log
        
        # Start the bot
        run_bot()
        
    except Exception as e:
        # Log errors with full traceback for debugging
        error_msg = f"Error starting Telegram bot: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", flush=True)  # Backup error log

if __name__ == '__main__':
    try:
        # Log application startup
        logger.info("=== Starting Coupon Manager Application ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}")
        logger.info(f"Current working directory: {os.getcwd()}")
        
        # Backup logs for production environments that might filter logging
        print("=== Starting Coupon Manager Application ===", flush=True)
        print(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}", flush=True)
        
        # Create and start Telegram bot process
        logger.info("Creating Telegram bot process...")
        bot_process = multiprocessing.Process(target=start_telegram_bot)
        bot_process.daemon = True  # Process will terminate when main app terminates
        bot_process.start()
        
        logger.info(f"Telegram bot process started with PID: {bot_process.pid}")
        print(f"Telegram bot process started with PID: {bot_process.pid}", flush=True)
        
        # Start Flask server
        logger.info("Starting Flask server on 0.0.0.0:10000")
        print("Starting Flask server on 0.0.0.0:10000", flush=True)
        
        # Run Flask app
        app.run(
            host='0.0.0.0', 
            port=10000, 
            debug=False,  # Always False for production
            use_reloader=False  # Prevents issues with multiprocessing
        )
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        print("Application interrupted by user", flush=True)
        
    except Exception as e:
        # Log critical errors that prevent app startup
        error_msg = f"Critical error starting application: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"CRITICAL ERROR: {error_msg}", flush=True)
        sys.exit(1)
        
    finally:
        logger.info("Application shutdown complete")
        print("Application shutdown complete", flush=True)