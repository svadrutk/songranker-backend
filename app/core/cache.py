import asyncio
import json
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, TypeVar
import logging
from fastapi import BackgroundTasks

from app.core.queue import get_async_redis

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

    async def _update_cache_stores(self, key: str, data: Any, expires_at: datetime, ttl_seconds: int, swr_ttl_seconds: int):
        """Update both memory and Redis caches."""
        self._update_memory(key, data, expires_at)
        
        # Save to Redis with SWR window buffer
        redis_ttl = ttl_seconds + swr_ttl_seconds
        entry = {
            "data": data,
            "expires_at": expires_at.isoformat()
        }
        redis = get_async_redis()
        await redis.set(f"cache:{key}", json.dumps(entry), ex=redis_ttl)

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Any],
        ttl_seconds: int = 3600,
        swr_ttl_seconds: int = 86400, # 24 hours
        background_tasks: Optional[BackgroundTasks] = None,
        negative_ttl_seconds: int = 300, # 5 minutes for None results
        return_metadata: bool = False,
        memory_ttl_seconds: Optional[int] = None
    ) -> Any:
        """
        Get data from cache (Memory -> Redis) or fetch from source.
        Supports Stale-While-Revalidate, Request Coalescing, and Bounded LRU.
        
        If return_metadata is True, returns (data, metadata_dict)
        If memory_ttl_seconds is provided, the memory cache will expire sooner than Redis.
        """
        now = datetime.now(timezone.utc)
        metadata = {"is_hit": False, "is_stale": False}

        # 1. Fast Path: Memory Hit
        if key in self._memory_cache:
            data, expires_at = self._memory_cache[key]
            self._memory_cache.move_to_end(key)
            
            if now < expires_at:
                logger.debug(f"Memory hit: {key}")
                metadata["is_hit"] = True
                return (data, metadata) if return_metadata else data
            
            # SWR: Return stale and refresh in background if not already in flight
            if background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds)):
                async with self._lock:
                    if key not in self._in_flight:
                        logger.info(f"Memory SWR trigger: {key}")
                        background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds, swr_ttl_seconds)
                
                metadata["is_hit"] = True
                metadata["is_stale"] = True
                return (data, metadata) if return_metadata else data

        # 2. Coalescing: Protect both Redis and Source Fetch
        async with self._lock:
            if key in self._in_flight:
                logger.info(f"Coalescing hit (waiting): {key}")
                future = self._in_flight[key]
            else:
                logger.debug(f"Cache miss, starting fetch: {key}")
                future = None
                self._in_flight[key] = asyncio.get_event_loop().create_future()
        
        if future:
            data = await future
            metadata["is_hit"] = True
            return (data, metadata) if return_metadata else data

        try:
            # 3. Check Redis
            redis = get_async_redis()
            cached_val = await redis.get(f"cache:{key}")
            if cached_val:
                entry = json.loads(cached_val)
                data, expires_at_str = entry.get("data"), entry.get("expires_at")
                
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    
                    # If memory_ttl is set, cap the memory expiration
                    mem_expires_at = expires_at
                    if memory_ttl_seconds:
                        mem_expires_at = min(expires_at, now + timedelta(seconds=memory_ttl_seconds))
                    
                    self._update_memory(key, data, mem_expires_at)
                    
                    is_expired = now >= expires_at
                    within_swr = background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds))
                    
                    if not is_expired or within_swr:
                        if is_expired and background_tasks:
                            logger.info(f"Redis SWR trigger: {key}")
                            background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds, swr_ttl_seconds)
                        
                        logger.info(f"Redis hit: {key}")
                        await self._resolve_future(key, data)
                        metadata["is_hit"] = True
                        metadata["is_stale"] = is_expired
                        return (data, metadata) if return_metadata else data

            # 4. Fetch from source
            logger.info(f"Fetching from source: {key}")
            data = await fetcher()
            
            # Save to cache (Negative caching if data is None)
            actual_ttl = ttl_seconds if data is not None else negative_ttl_seconds
            expires_at = now + timedelta(seconds=actual_ttl)
            
            # Memory expiration (possibly capped)
            mem_expires_at = expires_at
            if memory_ttl_seconds:
                mem_expires_at = min(expires_at, now + timedelta(seconds=memory_ttl_seconds))

            await self._update_cache_stores(key, data, expires_at, actual_ttl, swr_ttl_seconds)
            # Override memory expiration if we have a custom memory TTL
            if memory_ttl_seconds:
                self._update_memory(key, data, mem_expires_at)
                
            await self._resolve_future(key, data)
            return (data, metadata) if return_metadata else data

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

    async def _refresh_cache(self, key: str, fetcher: Callable[[], Any], ttl_seconds: int, swr_ttl_seconds: int = 86400):
        """Background task to refresh the cache."""
        try:
            # Check in-flight to avoid redundant refreshes
            async with self._lock:
                if key in self._in_flight:
                    return
                self._in_flight[key] = asyncio.get_event_loop().create_future()

            data = await fetcher()
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl_seconds)
            
            await self._update_cache_stores(key, data, expires_at, ttl_seconds, swr_ttl_seconds)
            await self._resolve_future(key, data)
        except BaseException as e:
            if not isinstance(e, asyncio.CancelledError):
                logger.warning(f"Background refresh failed for {key}: {e}")
            await self._reject_future(key, e)

    async def delete(self, key: str):
        """Invalidate a specific cache key."""
        async with self._lock:
            self._memory_cache.pop(key, None)
            
        redis = get_async_redis()
        await redis.delete(f"cache:{key}")
        logger.info(f"Invalidated cache key: {key}")

    async def delete_pattern(self, pattern: str):
        """
        Invalidate keys matching a pattern.
        Note: pattern should not include 'cache:' prefix.
        """
        # Memory cache invalidation
        async with self._lock:
            import fnmatch
            keys_to_del = [k for k in self._memory_cache.keys() if fnmatch.fnmatch(k, pattern)]
            for k in keys_to_del:
                self._memory_cache.pop(k, None)
        
        # Redis invalidation
        redis = get_async_redis()
        cursor = 0
        redis_pattern = f"cache:{pattern}"
        while True:
            cursor, keys = await redis.scan(cursor, match=redis_pattern, count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
        
        logger.info(f"Invalidated cache pattern: {pattern}")

cache = HybridCache()
