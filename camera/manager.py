"""
Camera Manager
Handles multiple camera sources with auto-reconnection and health monitoring
"""

import cv2
import asyncio
import logging
from typing import Optional, Dict, Callable
from datetime import datetime
import numpy as np
from queue import Queue, Full
from threading import Thread, Event as ThreadEvent

from core.config import CameraConfig
from core.events import FrameCapturedEvent, EventType


logger = logging.getLogger(__name__)


class CameraStream:
    """Individual camera stream handler"""
    
    def __init__(self, config: CameraConfig, frame_queue: Queue, 
                 event_callback: Optional[Callable] = None):
        self.config = config
        self.frame_queue = frame_queue
        self.event_callback = event_callback
        
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        self.is_connected = False
        self.stop_event = ThreadEvent()
        self.thread: Optional[Thread] = None
        
        self.frame_count = 0
        self.dropped_frames = 0
        self.last_frame_time: Optional[datetime] = None
        self.reconnect_attempts = 0
        self.max_reconnect_delay = 60  # seconds
        
        logger.info(f"Camera {config.id} ({config.name}) initialized")
    
    def start(self):
        """Start camera capture thread"""
        if self.is_running:
            logger.warning(f"Camera {self.config.id} already running")
            return
        
        self.is_running = True
        self.stop_event.clear()
        self.thread = Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        logger.info(f"Camera {self.config.id} capture thread started")
    
    def stop(self):
        """Stop camera capture"""
        if not self.is_running:
            return
        
        logger.info(f"Stopping camera {self.config.id}")
        self.is_running = False
        self.stop_event.set()
        
        if self.thread:
            self.thread.join(timeout=5.0)
        
        self._disconnect()
        logger.info(f"Camera {self.config.id} stopped")
    
    def _connect(self) -> bool:
        """Establish camera connection"""
        try:
            # Determine source type
            if self.config.is_usb:
                source = int(self.config.source)
            elif self.config.is_rtsp:
                source = self.config.source
            else:
                # File path or other
                source = self.config.source
            
            logger.info(f"Connecting to camera {self.config.id}: {source}")
            
            self.cap = cv2.VideoCapture(source)
            
            # Set camera properties
            if not self.config.is_rtsp:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                self.cap.set(cv2.CAP_PROP_FPS, self.config.fps)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize latency
            
            # Test read
            ret, frame = self.cap.read()
            if not ret or frame is None:
                logger.error(f"Camera {self.config.id}: Failed test read")
                self._disconnect()
                return False
            
            self.is_connected = True
            self.reconnect_attempts = 0
            
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            logger.info(
                f"Camera {self.config.id} connected: "
                f"{actual_width}x{actual_height} @ {actual_fps} FPS"
            )
            
            # Emit connection event
            if self.event_callback:
                event = FrameCapturedEvent(
                    event_type=EventType.CAMERA_CONNECTED,
                    camera_id=self.config.id,
                    width=actual_width,
                    height=actual_height,
                    metadata={'name': self.config.name}
                )
                self.event_callback(event)
            
            return True
            
        except Exception as e:
            logger.error(f"Camera {self.config.id} connection error: {e}")
            self._disconnect()
            return False
    
    def _disconnect(self):
        """Release camera resources"""
        if self.cap:
            self.cap.release()
            self.cap = None
        
        was_connected = self.is_connected
        self.is_connected = False
        
        if was_connected and self.event_callback:
            event = FrameCapturedEvent(
                event_type=EventType.CAMERA_DISCONNECTED,
                camera_id=self.config.id,
                metadata={'name': self.config.name}
            )
            self.event_callback(event)
    
    def _capture_loop(self):
        """Main capture loop with auto-reconnection"""
        logger.info(f"Camera {self.config.id} capture loop starting")
        
        while self.is_running and not self.stop_event.is_set():
            # Connect if not connected
            if not self.is_connected:
                if self._connect():
                    continue
                else:
                    # Exponential backoff
                    delay = min(2 ** self.reconnect_attempts, self.max_reconnect_delay)
                    logger.warning(
                        f"Camera {self.config.id} reconnect in {delay}s "
                        f"(attempt {self.reconnect_attempts + 1})"
                    )
                    self.reconnect_attempts += 1
                    self.stop_event.wait(delay)
                    continue
            
            # Capture frame
            try:
                ret, frame = self.cap.read()
                
                if not ret or frame is None:
                    logger.warning(f"Camera {self.config.id} frame read failed")
                    self._disconnect()
                    continue
                
                # Try to push frame to queue
                try:
                    self.frame_queue.put_nowait({
                        'camera_id': self.config.id,
                        'frame': frame,
                        'timestamp': datetime.now(),
                        'frame_id': self.frame_count
                    })
                    self.frame_count += 1
                    self.last_frame_time = datetime.now()
                    
                except Full:
                    # Queue full, drop frame
                    self.dropped_frames += 1
                    if self.dropped_frames % 100 == 0:
                        logger.warning(
                            f"Camera {self.config.id}: Dropped {self.dropped_frames} frames"
                        )
                
                # Frame rate control
                if self.config.fps > 0:
                    self.stop_event.wait(1.0 / self.config.fps)
                
            except Exception as e:
                logger.error(f"Camera {self.config.id} capture error: {e}")
                self._disconnect()
                self.stop_event.wait(1.0)
        
        logger.info(f"Camera {self.config.id} capture loop ended")
    
    def get_stats(self) -> Dict:
        """Get camera statistics"""
        return {
            'camera_id': self.config.id,
            'name': self.config.name,
            'connected': self.is_connected,
            'running': self.is_running,
            'frames_captured': self.frame_count,
            'frames_dropped': self.dropped_frames,
            'last_frame': self.last_frame_time.isoformat() if self.last_frame_time else None,
            'reconnect_attempts': self.reconnect_attempts
        }


class CameraManager:
    """Manages multiple camera streams"""
    
    def __init__(self, frame_queue: Queue, event_callback: Optional[Callable] = None):
        self.frame_queue = frame_queue
        self.event_callback = event_callback
        self.cameras: Dict[int, CameraStream] = {}
        logger.info("Camera Manager initialized")
    
    def add_camera(self, config: CameraConfig) -> bool:
        """Add and start a camera"""
        if config.id in self.cameras:
            logger.warning(f"Camera {config.id} already exists")
            return False
        
        if not config.enabled:
            logger.info(f"Camera {config.id} disabled, skipping")
            return False
        
        stream = CameraStream(config, self.frame_queue, self.event_callback)
        self.cameras[config.id] = stream
        stream.start()
        
        return True
    
    def remove_camera(self, camera_id: int):
        """Remove and stop a camera"""
        if camera_id not in self.cameras:
            logger.warning(f"Camera {camera_id} not found")
            return
        
        stream = self.cameras.pop(camera_id)
        stream.stop()
        logger.info(f"Camera {camera_id} removed")
    
    def start_all(self):
        """Start all camera streams"""
        for stream in self.cameras.values():
            if not stream.is_running:
                stream.start()
    
    def stop_all(self):
        """Stop all camera streams"""
        logger.info("Stopping all cameras")
        for stream in self.cameras.values():
            stream.stop()
    
    def get_camera_stats(self, camera_id: Optional[int] = None) -> Dict:
        """Get statistics for one or all cameras"""
        if camera_id is not None:
            if camera_id in self.cameras:
                return self.cameras[camera_id].get_stats()
            return {}
        
        return {
            cam_id: stream.get_stats()
            for cam_id, stream in self.cameras.items()
        }
    
    def is_any_connected(self) -> bool:
        """Check if any camera is connected"""
        return any(stream.is_connected for stream in self.cameras.values())
    
    def get_frame_rate(self, camera_id: int) -> float:
        """Get actual frame rate for a camera"""
        if camera_id not in self.cameras:
            return 0.0
        
        stream = self.cameras[camera_id]
        if not stream.last_frame_time:
            return 0.0
        
        # Simple estimation based on frame count and time
        # More sophisticated tracking could be added
        return stream.config.fps
    
    def __len__(self) -> int:
        return len(self.cameras)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()