"""
Rate limiting middleware for MERID APIs
Provides protection against high-volume requests and abuse
"""

import time
import asyncio
from typing import Dict, Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict, deque
from utils.logger import get_logger

logger = get_logger("rate_limiter")

class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using sliding window algorithm
    """
    
    def __init__(self, app, calls: int = 100, period: int = 60):
        """
        Initialize rate limiter
        
        Args:
            app: FastAPI application
            calls: Maximum number of requests allowed
            period: Time period in seconds
        """
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.clients: Dict[str, deque] = defaultdict(deque)
        self.cleanup_task = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to clean up old entries"""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._cleanup_old_entries())
    
    async def _cleanup_old_entries(self):
        """Clean up old client entries periodically"""
        while True:
            try:
                await asyncio.sleep(60)  # Clean every minute
                current_time = time.time()
                
                # Remove old entries from all clients
                for client_id, requests in list(self.clients.items()):
                    # Remove requests older than the period
                    while requests and requests[0] <= current_time - self.period:
                        requests.popleft()
                    
                    # Remove empty client entries
                    if not requests:
                        del self.clients[client_id]
                        
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {e}")
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request"""
        # Use IP address as client identifier
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    async def dispatch(self, request: Request, call_next):
        """Process request through rate limiter"""
        client_id = self._get_client_id(request)
        current_time = time.time()
        
        # Get client's request history
        client_requests = self.clients[client_id]
        
        # Remove old requests outside the time window
        while client_requests and client_requests[0] <= current_time - self.period:
            client_requests.popleft()
        
        # Check if client has exceeded rate limit
        if len(client_requests) >= self.calls:
            logger.warning(f"Rate limit exceeded for client {client_id}: {len(client_requests)}/{self.calls}")
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {self.calls} requests per {self.period} seconds."
            )
        
        # Add current request to history
        client_requests.append(current_time)
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.calls - len(client_requests)))
        response.headers["X-RateLimit-Reset"] = str(int(current_time + self.period))
        
        return response

class APIRateLimiter:
    """
    API-specific rate limiter for different endpoints
    """
    
    def __init__(self):
        self.limits = {
            "/api/v1/phase0/trial/record-weekly-decision": {"calls": 20, "period": 60},
            "/api/v1/phase0/trial/start": {"calls": 5, "period": 300},
            "/api/v1/phase0/experiment/weekly-decision": {"calls": 20, "period": 60},
            "/api/v1/phase0/experiment/start": {"calls": 5, "period": 300},
        }
        self.clients: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
    
    def check_rate_limit(self, client_id: str, endpoint: str) -> bool:
        """Check if client is within rate limits for endpoint"""
        if endpoint not in self.limits:
            return True  # No limit for this endpoint
        
        limit_config = self.limits[endpoint]
        calls = limit_config["calls"]
        period = limit_config["period"]
        
        client_requests = self.clients[client_id][endpoint]
        current_time = time.time()
        
        # Remove old requests
        while client_requests and client_requests[0] <= current_time - period:
            client_requests.popleft()
        
        # Check limit
        return len(client_requests) < calls
    
    def record_request(self, client_id: str, endpoint: str):
        """Record a request for rate limiting"""
        if endpoint in self.limits:
            self.clients[client_id][endpoint].append(time.time())
    
    def get_rate_limit_info(self, client_id: str, endpoint: str) -> Dict[str, int]:
        """Get rate limit information for client and endpoint"""
        if endpoint not in self.limits:
            return {"limit": -1, "remaining": -1, "reset": -1}
        
        limit_config = self.limits[endpoint]
        calls = limit_config["calls"]
        period = limit_config["period"]
        
        client_requests = self.clients[client_id][endpoint]
        current_time = time.time()
        
        # Remove old requests
        while client_requests and client_requests[0] <= current_time - period:
            client_requests.popleft()
        
        remaining = max(0, calls - len(client_requests))
        reset_time = int(current_time + period)
        
        return {
            "limit": calls,
            "remaining": remaining,
            "reset": reset_time
        }

# Global rate limiter instance
api_rate_limiter = APIRateLimiter()
