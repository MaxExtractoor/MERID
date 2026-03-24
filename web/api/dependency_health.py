"""HTTP surface for dependency health."""

from fastapi import APIRouter

from merid.monitoring.dependency_health import get_dependencies_health

router = APIRouter(prefix="/api/v1", tags=["dependency-health"])


@router.get("/dependencies/health")
async def dependencies_health():
    """Expose dependency health snapshot."""
    return get_dependencies_health()
