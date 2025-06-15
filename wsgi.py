# wsgi.py
import os
import sys
import logging
import threading
import asyncio
import signal
from app import create_app

def setup_production_logging():
    """
    Setup logging configuration that works in both development and production environments.
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
    
    logging.info("=== Logging configured for production deployment ===")

# Initialize logging before anything else
setup_production_logging()

# Create logger for this module
logger = logging.getLogger(__name__)

# Create Flask application
app = create_app()

def start_flask_server():
    """
    Start Flask server in a separate thread.
    """
    try:
        logger.info("Starting Flask server in separate thread...")
        print("Starting Flask server in separate thread...", flush=True)
        
        app.run(
            host='0.0.0.0', 
            port=10000, 
            debug=False,
            use_reloader=False,
            threaded=True
        )
        
    except Exception as e:
        error_msg = f"Error starting Flask server: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", flush=True)

def start_telegram_bot_async():
    """
    Start Telegram bot with async/await support in main thread.
    """
    try:
        logger.info("Starting Telegram bot in main thread...")
        print("Starting Telegram bot in main thread...", flush=True)
        
        # Import here to avoid circular imports
        from telegram_bot import create_bot_application
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create bot application
        app_bot = create_bot_application()
        
        if not app_bot:
            error_msg = "Failed to create Telegram bot application"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}", flush=True)
            return
            
        logger.info("Bot application created, starting polling...")
        print("Bot application created, starting polling...", flush=True)
        
        # Run polling in the event loop
        app_bot.run_polling(allowed_updates=['message', 'callback_query'])
        
    except Exception as e:
        error_msg = f"Error starting Telegram bot: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", flush=True)
        # Don't exit here, let Flask continue running
        return

if __name__ == '__main__':
    try:
        # Log application startup
        logger.info("=== Starting Coupon Manager Application ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}")
        logger.info(f"Current working directory: {os.getcwd()}")
        
        print("=== Starting Coupon Manager Application ===", flush=True)
        print(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}", flush=True)
        
        # Check if Telegram bot is enabled
        enable_bot = os.getenv('ENABLE_BOT', 'true').lower() == 'true'
        
        if enable_bot:
            # Start Flask in background thread
            logger.info("Creating Flask server thread...")
            flask_thread = threading.Thread(target=start_flask_server, daemon=True)
            flask_thread.start()
            
            logger.info("Flask server thread started, starting Telegram bot in main thread...")
            print("Flask server thread started, starting Telegram bot in main thread...", flush=True)
            
            # Start Telegram bot in main thread (required for asyncio signal handlers)
            start_telegram_bot_async()
        else:
            logger.info("Telegram bot is disabled, starting only Flask server")
            print("Telegram bot is disabled, starting only Flask server", flush=True)
            
            # Just run Flask server
            app.run(
                host='0.0.0.0', 
                port=10000, 
                debug=False,
                use_reloader=False,
                threaded=True
            )
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        print("Application interrupted by user", flush=True)
        
    except Exception as e:
        error_msg = f"Critical error starting application: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"CRITICAL ERROR: {error_msg}", flush=True)
        sys.exit(1)
        
    finally:
        logger.info("Application shutdown complete")
        print("Application shutdown complete", flush=True)

# For production servers like Gunicorn that import this file
else:
    logger.info("WSGI mode detected - Telegram bot will need to run separately or use webhook")
    print("WSGI mode detected - Telegram bot will need to run separately or use webhook", flush=True)