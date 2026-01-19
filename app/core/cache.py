import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, Generic, cast
import logging
from fastapi import BackgroundTasks

from app.clients.supabase_db import supabase_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

class HybridCache:
    def __init__(self, max_size: int = 10000):
        # Memory cache: key -> (data, expires_at) using OrderedDict for LRU
        self._memory_cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._max_size = max_size
        # In-flight requests: key -> Future
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Any],
        ttl_seconds: int = 3600,
        swr_ttl_seconds: int = 86400, # 24 hours
        background_tasks: Optional[BackgroundTasks] = None,
        negative_ttl_seconds: int = 300 # 5 minutes for None results
    ) -> Any:
        """
        Get data from cache (Memory -> Supabase) or fetch from source.
        Supports Stale-While-Revalidate, Request Coalescing, and Bounded LRU.
        """
        now = datetime.now(timezone.utc)

        # 1. Fast Path: Memory Hit
        if key in self._memory_cache:
            data, expires_at = self._memory_cache[key]
            self._memory_cache.move_to_end(key)
            
            if now < expires_at:
                logger.debug(f"Memory hit: {key}")
                return data
            
            # SWR: Return stale and refresh in background if not already in flight
            if background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds)):
                async with self._lock:
                    if key not in self._in_flight:
                        logger.info(f"Memory SWR trigger: {key}")
                        background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds)
                return data

        # 2. Coalescing: Protect both Supabase and Source Fetch
        async with self._lock:
            if key in self._in_flight:
                logger.info(f"Coalescing hit (waiting): {key}")
                future = self._in_flight[key]
            else:
                logger.debug(f"Cache miss, starting fetch: {key}")
                future = None
                self._in_flight[key] = asyncio.get_event_loop().create_future()
        
        if future:
            return await future

        try:
            # 3. Check Supabase
            db_cache = await supabase_client.get_cache(key)
            if db_cache:
                data = db_cache.get("data")
                expires_at_str = db_cache.get("expires_at")
                if expires_at_str:
                    expires_at = datetime.fromisoformat(cast(str, expires_at_str))
                    self._update_memory(key, data, expires_at)
                    
                    # If within expiry or within SWR window
                    is_expired = now >= expires_at
                    within_swr = background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds))
                    
                    if not is_expired or within_swr:
                        # Trigger background refresh if expired but within SWR
                        if is_expired and background_tasks:
                            logger.info(f"Supabase SWR trigger: {key}")
                            background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds)
                        
                        logger.info(f"Supabase hit: {key}")
                        await self._resolve_future(key, data)
                        return data

            # 4. Fetch from source
            logger.info(f"Fetching from source: {key}")
            data = await fetcher()
            logger.info(f"Source fetch complete: {key}")
            
            # Save to cache (Negative caching if data is None)
            actual_ttl = ttl_seconds if data is not None else negative_ttl_seconds
            expires_at = now + timedelta(seconds=actual_ttl)
            
            self._update_memory(key, data, expires_at)
            await supabase_client.set_cache(key, data, expires_at)
            
            await self._resolve_future(key, data)
            return data

        except BaseException as e:
            logger.error(f"Error in get_or_fetch for {key}: {e}")
            await self._reject_future(key, e)
            raise

    async def _resolve_future(self, key: str, result: Any):
        """Safely resolve an in-flight future."""
        async with self._lock:
            future = self._in_flight.pop(key, None)
            if future and not future.done():
                future.set_result(result)

    async def _reject_future(self, key: str, exception: BaseException):
        """Safely reject an in-flight future."""
        async with self._lock:
            future = self._in_flight.pop(key, None)
            if future and not future.done():
                if isinstance(exception, asyncio.CancelledError):
                    future.cancel()
                else:
                    future.set_exception(exception)


    def _update_memory(self, key: str, data: Any, expires_at: datetime):
        """Internal helper to update memory cache with LRU eviction."""
        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)
        self._memory_cache[key] = (data, expires_at)
        
        # Evict oldest if limit reached
        if len(self._memory_cache) > self._max_size:
            self._memory_cache.popitem(last=False)

    async def _refresh_cache(self, key: str, fetcher: Callable[[], Any], ttl_seconds: int):
        """Background task to refresh the cache."""
        try:
            # Check in-flight to avoid redundant refreshes
            async with self._lock:
                if key in self._in_flight:
                    return
                self._in_flight[key] = asyncio.get_event_loop().create_future()

            data = await fetcher()
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            
            self._update_memory(key, data, expires_at)
            await supabase_client.set_cache(key, data, expires_at)
            
            await self._resolve_future(key, data)
        except BaseException as e:
            if not isinstance(e, asyncio.CancelledError):
                logger.warning(f"Background refresh failed for {key}: {e}")
            await self._reject_future(key, e)

cache = HybridCache()
