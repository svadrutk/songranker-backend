#!/usr/bin/env python
import os
import logging
import sys
import argparse

# Fix for macOS fork safety issue with OBJC - must be set before other imports
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

# Configure logging for the worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

from rq import Worker  # noqa: E402
from app.core.queue import sync_redis_conn  # noqa: E402

# This script starts an RQ worker
# It can listen to different queues based on command-line arguments

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Start an RQ worker')
    parser.add_argument(
        '--queues',
        type=str,
        default='default',
        help='Comma-separated list of queue names to listen to (default: default)'
    )
    args = parser.parse_args()
    
    # Parse queue names
    queue_names = [q.strip() for q in args.queues.split(',')]
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting RQ worker listening on queues: {queue_names}")
    
    # Start the worker using the existing sync connection
    worker = Worker(queue_names, connection=sync_redis_conn)
    worker.work()
