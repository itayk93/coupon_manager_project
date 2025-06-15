# wsgi.py
import os
import sys
import logging
import threading
import asyncio
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

def start_telegram_bot_thread():
    """
    Start Telegram bot in a separate thread with asyncio loop.
    This works around the signal handler limitation.
    """
    try:
        logger.info("Starting Telegram bot in background thread...")
        print("Starting Telegram bot in background thread...", flush=True)
        
        # Import here to avoid circular imports
        from telegram_bot import create_bot_application
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create bot application
        app_bot = create_bot_application()
        
        if app_bot:
            logger.info("Bot application created, starting polling without signal handlers...")
            print("Bot application created, starting polling without signal handlers...", flush=True)
            
            # Start polling without signal handlers (to avoid main thread requirement)
            async def run_polling():
                await app_bot.initialize()
                await app_bot.start()
                await app_bot.updater.start_polling(allowed_updates=['message', 'callback_query'])
                
                # Keep the bot running
                try:
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                finally:
                    await app_bot.stop()
                    await app_bot.shutdown()
            
            # Run the bot
            loop.run_until_complete(run_polling())
        else:
            logger.warning("Failed to create bot application")
            print("Failed to create bot application", flush=True)
        
    except Exception as e:
        error_msg = f"Error starting Telegram bot: {str(e)}"
        logger.error(error_msg, exc_info=True)
        print(f"ERROR: {error_msg}", flush=True)

def start_bot_if_enabled():
    """
    Start bot if enabled, regardless of execution mode.
    """
    enable_bot = os.getenv('ENABLE_BOT', 'true').lower() == 'true'
    
    if enable_bot:
        logger.info("Starting Telegram bot in background thread...")
        print("Starting Telegram bot in background thread...", flush=True)
        
        bot_thread = threading.Thread(target=start_telegram_bot_thread, daemon=True)
        bot_thread.start()
        
        logger.info("Telegram bot thread started successfully")
        print("Telegram bot thread started successfully", flush=True)
    else:
        logger.info("Telegram bot is disabled via ENABLE_BOT environment variable")
        print("Telegram bot is disabled via ENABLE_BOT environment variable", flush=True)

if __name__ == '__main__':
    try:
        # Log application startup
        logger.info("=== Starting Coupon Manager Application (Direct Mode) ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}")
        logger.info(f"Current working directory: {os.getcwd()}")
        
        print("=== Starting Coupon Manager Application (Direct Mode) ===", flush=True)
        print(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}", flush=True)
        
        # Start bot
        start_bot_if_enabled()
        
        # Start Flask server
        logger.info("Starting Flask server on 0.0.0.0:10000")
        print("Starting Flask server on 0.0.0.0:10000", flush=True)
        
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

# For production servers like Gunicorn - ALWAYS start the bot here too
else:
    logger.info("=== Starting Coupon Manager Application (WSGI Mode) ===")
    logger.info(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}")
    print("=== Starting Coupon Manager Application (WSGI Mode) ===", flush=True)
    print(f"Environment: {'PRODUCTION' if os.getenv('FLASK_ENV') == 'production' else 'DEVELOPMENT'}", flush=True)
    
    # Start bot in WSGI mode too
    start_bot_if_enabled()