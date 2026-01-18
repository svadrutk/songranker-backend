import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, Generic, cast
import logging

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
        background_tasks: Optional[Any] = None,
        negative_ttl_seconds: int = 300 # 5 minutes for None results
    ) -> Any:
        """
        Get data from cache (Memory -> Supabase) or fetch from source.
        Supports Stale-While-Revalidate, Request Coalescing, and Bounded LRU.
        """
        now = datetime.now(timezone.utc)

        # 1. Check Memory (LRU)
        if key in self._memory_cache:
            data, expires_at = self._memory_cache[key]
            # Move to end (most recently used)
            self._memory_cache.move_to_end(key)
            
            if now < expires_at:
                return data
            # If expired but within SWR, return stale and refresh in background
            if background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds)):
                background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds)
                return data

        # 2. Check Supabase
        db_cache = await supabase_client.get_cache(key)
        if db_cache:
            data = db_cache.get("data")
            expires_at_str = db_cache.get("expires_at")
            if expires_at_str:
                expires_at = datetime.fromisoformat(cast(str, expires_at_str))
                
                # Update memory cache with LRU management
                self._update_memory(key, data, expires_at)

                if now < expires_at:
                    return data
                
                # If expired but within SWR
                if background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds)):
                    background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds)
                    return data

        # 3. Request Coalescing
        async with self._lock:
            if key in self._in_flight:
                return await self._in_flight[key]
            
            self._in_flight[key] = asyncio.get_event_loop().create_future()

        # 4. Fetch from source
        try:
            data = await fetcher()
            
            # Save to cache (Negative caching if data is None)
            actual_ttl = ttl_seconds if data is not None else negative_ttl_seconds
            expires_at = now + timedelta(seconds=actual_ttl)
            
            self._update_memory(key, data, expires_at)
            
            # Save to Supabase
            await supabase_client.set_cache(key, data, expires_at)
            
            # Resolve the future
            async with self._lock:
                future = self._in_flight.pop(key)
                future.set_result(data)
            
            return data
        except Exception as e:
            async with self._lock:
                future = self._in_flight.pop(key, None)
                if future:
                    future.set_exception(e)
            raise e

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
            
            self._memory_cache[key] = (data, expires_at)
            await supabase_client.set_cache(key, data, expires_at)
            
            async with self._lock:
                future = self._in_flight.pop(key)
                future.set_result(data)
        except Exception:
            # Log failure if needed, but don't break background task
            async with self._lock:
                self._in_flight.pop(key, None)

cache = HybridCache()
