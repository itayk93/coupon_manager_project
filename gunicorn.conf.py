import multiprocessing
import os

# Number of worker processes
workers = multiprocessing.cpu_count() * 2 + 1

# Worker class
worker_class = 'sync'

# Timeout for worker processes
timeout = 120

# Maximum number of requests a worker will process before restarting
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Process naming
proc_name = 'coupon_manager'

# Preload app
preload_app = True

def post_fork(server, worker):
    """Initialize bot process after worker fork"""
    from wsgi import init_bot 