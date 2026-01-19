#!/usr/bin/env python
from rq import Worker
from app.core.queue import sync_redis_conn

# This script starts an RQ worker
# It listens for tasks on the 'default' queue

if __name__ == '__main__':
    # Start the worker using the existing sync connection
    worker = Worker(['default'], connection=sync_redis_conn)
    print("Starting RQ worker listening on 'default' queue...")
    worker.work()
