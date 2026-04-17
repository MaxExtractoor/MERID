"""
Simple test endpoint to serve a standalone predictions test page
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter()

@router.get("/test-predictions", response_class=HTMLResponse)
async def test_predictions_page():
    """Serve a simple test page for predictions"""
    template_path = Path(__file__).parent.parent / "templates" / "test_predictions.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()

@router.get("/dashboard-v2", response_class=HTMLResponse)
async def dashboard_v2_page():
    """Serve the new working dashboard v2"""
    template_path = Path(__file__).parent.parent / "templates" / "dashboard_v2.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()

@router.get("/dashboard-v2-full", response_class=HTMLResponse)
async def dashboard_v2_full_page():
    """Serve the comprehensive MERID Dashboard v2 control plane"""
    template_path = Path(__file__).parent.parent / "templates" / "dashboard_v2_full.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()
