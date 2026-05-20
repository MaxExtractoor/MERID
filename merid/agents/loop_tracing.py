"""
Main Loop Tracing Wrapper

Provides lightweight tracing for agent step/tick calls to identify
which agents are consuming time or blocking the loop.
"""

from __future__ import annotations

import time
import functools
from typing import Callable, Any
from datetime import datetime

from utils.logger import get_logger
from merid.agents.agent_metadata import get_agent_metadata_from_instance

logger = get_logger("merid.agents.loop_tracing")


def trace_agent_step(agent_instance: object = None, agent_name: str = None):
    """Decorator to trace agent step/tick calls with classification and timing.
    
    Args:
        agent_instance: Agent instance (for metadata extraction)
        agent_name: Agent name (fallback if instance not provided)
        
    Usage:
        @trace_agent_step(agent_instance=self)
        async def run_cycle(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            # Get agent metadata
            if agent_instance is not None:
                metadata = get_agent_metadata_from_instance(agent_instance)
                name = metadata.name
                classification = metadata.classification
                age_bucket = metadata.age_bucket
                tag = metadata.tag
                module_path = metadata.module_path
            elif agent_name is not None:
                name = agent_name
                classification = "unknown"
                age_bucket = "unknown"
                tag = None
                module_path = "unknown"
            else:
                # Try to get from self (first arg if method)
                if args and hasattr(args[0], '__class__'):
                    metadata = get_agent_metadata_from_instance(args[0])
                    name = metadata.name
                    classification = metadata.classification
                    age_bucket = metadata.age_bucket
                    tag = metadata.tag
                    module_path = metadata.module_path
                else:
                    name = "unknown"
                    classification = "unknown"
                    age_bucket = "unknown"
                    tag = None
                    module_path = "unknown"
            
            # Log entry
            ts_start = time.time()
            logger.info(
                f"[MAIN-LOOP] entering step agent={name} "
                f"classification={classification} age={age_bucket} tag={tag} "
                f"module={module_path} ts={datetime.now().isoformat()}"
            )
            
            try:
                # Execute the function
                result = await func(*args, **kwargs)
                
                # Log success
                duration_ms = (time.time() - ts_start) * 1000
                logger.info(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age={age_bucket} tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=ok"
                )
                
                return result
                
            except Exception as e:
                # Log error
                duration_ms = (time.time() - ts_start) * 1000
                logger.error(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age={age_bucket} tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=error error={type(e).__name__}: {e}"
                )
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            # Get agent metadata
            if agent_instance is not None:
                metadata = get_agent_metadata_from_instance(agent_instance)
                name = metadata.name
                classification = metadata.classification
                age_bucket = metadata.age_bucket
                tag = metadata.tag
                module_path = metadata.module_path
            elif agent_name is not None:
                name = agent_name
                classification = "unknown"
                age_bucket = "unknown"
                tag = None
                module_path = "unknown"
            else:
                # Try to get from self (first arg if method)
                if args and hasattr(args[0], '__class__'):
                    metadata = get_agent_metadata_from_instance(args[0])
                    name = metadata.name
                    classification = metadata.classification
                    age_bucket = metadata.age_bucket
                    tag = metadata.tag
                    module_path = metadata.module_path
                else:
                    name = "unknown"
                    classification = "unknown"
                    age_bucket = "unknown"
                    tag = None
                    module_path = "unknown"
            
            # Log entry
            ts_start = time.time()
            logger.info(
                f"[MAIN-LOOP] entering step agent={name} "
                f"classification={classification} age={age_bucket} tag={tag} "
                f"module={module_path} ts={datetime.now().isoformat()}"
            )
            
            try:
                # Execute the function
                result = func(*args, **kwargs)
                
                # Log success
                duration_ms = (time.time() - ts_start) * 1000
                logger.info(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age={age_bucket} tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=ok"
                )
                
                return result
                
            except Exception as e:
                # Log error
                duration_ms = (time.time() - ts_start) * 1000
                logger.error(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age={age_bucket} tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=error error={type(e).__name__}: {e}"
                )
                raise
        
        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def trace_generic_step(name: str, classification: str = "unknown", tag: str = None):
    """Decorator for generic step tracing without agent instance.
    
    Args:
        name: Name of the step/function
        classification: Classification of the step
        tag: Optional tag (e.g., llm_mesh_v1)
        
    Usage:
        @trace_generic_step("reflection_load", "research_only", "reflection_v2")
        def load_reflections():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            ts_start = time.time()
            logger.info(
                f"[MAIN-LOOP] entering step agent={name} "
                f"classification={classification} age=unknown tag={tag} "
                f"module=unknown ts={datetime.now().isoformat()}"
            )
            
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - ts_start) * 1000
                logger.info(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age=unknown tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=ok"
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - ts_start) * 1000
                logger.error(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age=unknown tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=error error={type(e).__name__}: {e}"
                )
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            ts_start = time.time()
            logger.info(
                f"[MAIN-LOOP] entering step agent={name} "
                f"classification={classification} age=unknown tag={tag} "
                f"module=unknown ts={datetime.now().isoformat()}"
            )
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - ts_start) * 1000
                logger.info(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age=unknown tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=ok"
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - ts_start) * 1000
                logger.error(
                    f"[MAIN-LOOP] exiting step agent={name} "
                    f"classification={classification} age=unknown tag={tag} "
                    f"duration_ms={duration_ms:.2f} status=error error={type(e).__name__}: {e}"
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Import asyncio at module level for iscoroutinefunction check
import asyncio
