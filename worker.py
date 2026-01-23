#!/usr/bin/env python
import os
import logging
import sys

# Fix for macOS fork safety issue with OBJC - must be set before other imports
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Configure logging for the worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

from rq import Worker
from app.core.queue import sync_redis_conn

# This script starts an RQ worker
# It listens for tasks on the 'default' queue

if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    logger.info("Starting RQ worker listening on 'default' queue...")
    
    # Start the worker using the existing sync connection
    worker = Worker(['default'], connection=sync_redis_conn)
    worker.work()
