import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, Generic, cast
from app.clients.supabase_db import supabase_client

T = TypeVar("T")

class HybridCache:
    def __init__(self):
        # Memory cache: key -> (data, expires_at)
        self._memory_cache: Dict[str, tuple[Any, datetime]] = {}
        # In-flight requests: key -> Future
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Any],
        ttl_seconds: int = 3600,
        swr_ttl_seconds: int = 86400, # 24 hours
        background_tasks: Optional[Any] = None
    ) -> Any:
        """
        Get data from cache (Memory -> Supabase) or fetch from source.
        Supports Stale-While-Revalidate and Request Coalescing.
        """
        now = datetime.now(timezone.utc)

        # 1. Check Memory
        if key in self._memory_cache:
            data, expires_at = self._memory_cache[key]
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
            if data is not None and expires_at_str:
                expires_at = datetime.fromisoformat(cast(str, expires_at_str))
                
                # Update memory cache
                self._memory_cache[key] = (data, expires_at)

                if now < expires_at:
                    return data
                
                # If expired but within SWR
                if background_tasks and now < (expires_at + timedelta(seconds=swr_ttl_seconds)):
                    background_tasks.add_task(self._refresh_cache, key, fetcher, ttl_seconds)
                    return data

        # 3. Request Coalescing: Check if someone else is already fetching this
        async with self._lock:
            if key in self._in_flight:
                return await self._in_flight[key]
            
            # Create a future for this request
            self._in_flight[key] = asyncio.get_event_loop().create_future()

        # 4. Fetch from source
        try:
            data = await fetcher()
            
            # Save to cache
            expires_at = now + timedelta(seconds=ttl_seconds)
            self._memory_cache[key] = (data, expires_at)
            
            # Save to Supabase (we do this in the foreground here to ensure the first caller gets it, 
            # or we could do it in background if we prefer speed for the very first caller)
            await supabase_client.set_cache(key, data, expires_at)
            
            # Resolve the future for other waiters
            async with self._lock:
                future = self._in_flight.pop(key)
                future.set_result(data)
            
            return data
        except Exception as e:
            # Resolve future with exception if fetch fails
            async with self._lock:
                future = self._in_flight.pop(key, None)
                if future:
                    future.set_exception(e)
            raise e

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
