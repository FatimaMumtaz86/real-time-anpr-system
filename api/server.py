"""
FastAPI Backend for ANPR Dashboard
Provides REST API and WebSocket streaming for live updates
"""

import logging
import asyncio
import json
import cv2
import base64
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import numpy as np

from core.config import Config
from database.manager import DatabaseManager


logger = logging.getLogger(__name__)


# Request/Response Models
class EventResponse(BaseModel):
    id: int
    camera_id: int
    event_type: str
    vehicle_type: Optional[str]
    plate_text: Optional[str]
    plate_confidence: Optional[float]
    timestamp: str
    duration: Optional[float]


class StatsResponse(BaseModel):
    total_events: int
    total_entries: int
    total_exits: int
    cameras_online: int
    current_fps: float
    uptime_seconds: float


class CameraStatus(BaseModel):
    camera_id: int
    name: str
    connected: bool
    fps: float
    frames_captured: int


# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)


# Global instances
manager = ConnectionManager()
pipeline = None  # Will be set by main.py
db_manager = None


def create_app():
    """Create FastAPI application"""
    
    app = FastAPI(
        title="ANPR Dashboard API",
        description="Real-time vehicle detection and plate recognition",
        version="1.0.0"
    )

    # CORS middleware for React frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify exact origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add dashboard routes
    from api.routes import add_dashboard_routes
    add_dashboard_routes(app)

    # ============ REST API Endpoints ============

    @app.get("/")
    async def root():
        """API health check"""
        return {
            "status": "operational",
            "service": "ANPR Dashboard API",
            "version": "1.0.0"
        }

    @app.get("/api/stats", response_model=StatsResponse)
    async def get_stats():
        """Get system statistics"""
        if not pipeline:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        stats = pipeline.get_stats()
        db_stats = pipeline.database.get_stats()
        
        cameras_online = sum(
            1 for cam in stats['cameras'].values() 
            if cam.get('connected', False)
        )
        
        return StatsResponse(
            total_events=db_stats.get('total_events', 0),
            total_entries=db_stats.get('total_entries', 0),
            total_exits=db_stats.get('total_exits', 0),
            cameras_online=cameras_online,
            current_fps=stats.get('fps', 0),
            uptime_seconds=stats.get('uptime_seconds', 0)
        )

    @app.get("/api/events/recent", response_model=List[EventResponse])
    async def get_recent_events(limit: int = 50, camera_id: Optional[int] = None):
        """Get recent events"""
        if not pipeline:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        events = pipeline.database.get_recent_events(limit, camera_id)
        
        return [
            EventResponse(
                id=e['id'],
                camera_id=e['camera_id'],
                event_type=e['event_type'],
                vehicle_type=e.get('vehicle_type'),
                plate_text=e.get('plate_text'),
                plate_confidence=e.get('plate_confidence'),
                timestamp=e['timestamp'].isoformat() if isinstance(e['timestamp'], datetime) else e['timestamp'],
                duration=e.get('duration')
            )
            for e in events
        ]

    @app.get("/api/events/search")
    async def search_events(plate: str):
        """Search events by plate number"""
        if not pipeline:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        events = pipeline.database.get_events_by_plate(plate.upper())
        
        return [
            {
                "id": e['id'],
                "camera_id": e['camera_id'],
                "event_type": e['event_type'],
                "plate_text": e.get('plate_text'),
                "timestamp": e['timestamp'].isoformat() if isinstance(e['timestamp'], datetime) else e['timestamp']
            }
            for e in events
        ]

    @app.get("/api/cameras", response_model=List[CameraStatus])
    async def get_cameras():
        """Get camera status"""
        if not pipeline:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        stats = pipeline.get_stats()
        cameras = stats.get('cameras', {})
        
        return [
            CameraStatus(
                camera_id=cam['camera_id'],
                name=cam['name'],
                connected=cam['connected'],
                fps=pipeline.camera_manager.get_frame_rate(cam['camera_id']),
                frames_captured=cam['frames_captured']
            )
            for cam in cameras.values()
        ]

    @app.get("/api/events/stats/hourly")
    async def get_hourly_stats():
        """Get event statistics by hour (last 24 hours)"""
        if not pipeline:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        
        # This would require more sophisticated DB queries
        # For now, return simple aggregation
        events = pipeline.database.get_recent_events(1000)
        
        hourly = {}
        for event in events:
            timestamp = event['timestamp']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            
            hour_key = timestamp.strftime("%Y-%m-%d %H:00")
            if hour_key not in hourly:
                hourly[hour_key] = {'entries': 0, 'exits': 0}
            
            if event['event_type'] == 'entry':
                hourly[hour_key]['entries'] += 1
            else:
                hourly[hour_key]['exits'] += 1
        
        return hourly

    # ============ WebSocket Endpoints ============

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket):
        """
        WebSocket for live updates
        Sends: detections, events, stats in real-time
        """
        await manager.connect(websocket)
        
        try:
            while True:
                # Keep connection alive and wait for messages
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Send heartbeat
                    await websocket.send_json({"type": "heartbeat"})
                    continue
                
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            manager.disconnect(websocket)

    @app.websocket("/ws/video/{camera_id}")
    async def websocket_video(websocket: WebSocket, camera_id: int):
        """
        WebSocket for video streaming
        Sends JPEG frames encoded as base64
        """
        await websocket.accept()
        
        try:
            from queue import Queue, Empty
            
            # Create a frame buffer for this connection
            frame_buffer = Queue(maxsize=2)
            
            # Subscribe to frames from pipeline
            # (This would need to be implemented in the pipeline)
            
            while True:
                try:
                    # Get frame from buffer (if available)
                    # For now, we'll send a placeholder
                    await asyncio.sleep(0.05)  # ~20 FPS
                    
                    # TODO: Get actual frame from pipeline
                    # frame = frame_buffer.get_nowait()
                    # _, buffer = cv2.imencode('.jpg', frame)
                    # jpg_base64 = base64.b64encode(buffer).decode('utf-8')
                    
                    # await websocket.send_json({
                    #     "type": "frame",
                    #     "camera_id": camera_id,
                    #     "data": jpg_base64
                    # })
                    
                except Empty:
                    continue
                    
        except WebSocketDisconnect:
            logger.info(f"Video stream disconnected for camera {camera_id}")
        except Exception as e:
            logger.error(f"Video stream error: {e}")

    return app


# Broadcast helper for main pipeline to call
async def broadcast_event(event: Dict):
    """Called by pipeline when new event occurs"""
    await manager.broadcast({
        "type": "event",
        "data": event
    })


async def broadcast_detection(camera_id: int, detections: List[Dict]):
    """Called by pipeline for live detections"""
    await manager.broadcast({
        "type": "detections",
        "camera_id": camera_id,
        "count": len(detections),
        "data": detections
    })


async def broadcast_stats(stats: Dict):
    """Called by pipeline for system stats"""
    await manager.broadcast({
        "type": "stats",
        "data": stats
    })


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    config = Config.load()
    
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level="info"
    )