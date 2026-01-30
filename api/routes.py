"""
Simple static file server for dashboard
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path


def add_dashboard_routes(app: FastAPI):
    """Add dashboard serving routes to FastAPI app"""
    
    dashboard_path = Path(__file__).parent.parent / "ui" / "dashboard.html"
    
    @app.get("/dashboard")
    async def serve_dashboard():
        """Serve the dashboard HTML"""
        if dashboard_path.exists():
            return FileResponse(dashboard_path)
        return {"error": "Dashboard not found"}
    
    @app.get("/")
    async def root_redirect():
        """Redirect root to dashboard"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard")