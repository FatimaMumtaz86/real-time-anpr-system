"""
Main ANPR Pipeline
Orchestrates all components for end-to-end processing
"""

import logging
import cv2
import numpy as np
from queue import Queue, Empty
from threading import Thread, Event as ThreadEvent
from typing import Dict, List, Optional
from datetime import datetime
import time

from core.config import Config, SystemConfig
from core.events import Track
from camera.manager import CameraManager
from perception.detector import VehicleDetector
from tracking.engine import TrackingEngine
from ocr.engine import OCREngine
from events.engine import EventEngine
from database.manager import DatabaseManager


logger = logging.getLogger(__name__)


class ANPRPipeline:
    """Main processing pipeline"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        
        # Frame queue from cameras
        self.frame_queue = Queue(maxsize=config.frame_queue_size)
        
        # Components
        self.camera_manager = CameraManager(self.frame_queue)
        self.detector = VehicleDetector(config.detection)
        self.database = DatabaseManager(config.database)
        
        # Per-camera components
        self.trackers: Dict[int, TrackingEngine] = {}
        self.event_engines: Dict[int, EventEngine] = {}
        self.ocr_engines: Dict[int, OCREngine] = {}
        
        # Processing thread
        self.processor_thread: Optional[Thread] = None
        self.is_running = False
        self.stop_event = ThreadEvent()
        
        # Statistics
        self.total_frames = 0
        self.processed_frames = 0
        self.start_time = None
        
        # Initialize per-camera components
        for camera in config.cameras:
            if camera.enabled:
                self.trackers[camera.id] = TrackingEngine(config.tracking, camera.id)
                self.event_engines[camera.id] = EventEngine(config.events, camera.id)
                self.ocr_engines[camera.id] = OCREngine(config.ocr)
                
                # Register camera in DB
                self.database.insert_camera({
                    'id': camera.id,
                    'name': camera.name,
                    'source': camera.source,
                    'status': 'active'
                })
        
        logger.info("ANPR Pipeline initialized")
    
    def start(self):
        """Start the pipeline"""
        if self.is_running:
            logger.warning("Pipeline already running")
            return
        
        logger.info("Starting ANPR Pipeline")
        
        # Start cameras
        for camera in self.config.cameras:
            self.camera_manager.add_camera(camera)
        
        # Start processing thread
        self.is_running = True
        self.stop_event.clear()
        self.start_time = datetime.now()
        self.processor_thread = Thread(target=self._processing_loop, daemon=True)
        self.processor_thread.start()
        
        logger.info("Pipeline started successfully")
    
    def stop(self):
        """Stop the pipeline"""
        if not self.is_running:
            return
        
        logger.info("Stopping ANPR Pipeline")
        
        self.is_running = False
        self.stop_event.set()
        
        # Stop cameras
        self.camera_manager.stop_all()
        
        # Wait for processor
        if self.processor_thread:
            self.processor_thread.join(timeout=5.0)
        
        # Close database
        self.database.close()
        
        logger.info("Pipeline stopped")
    
    def _processing_loop(self):
        """Main processing loop"""
        logger.info("Processing loop started")
        
        while self.is_running and not self.stop_event.is_set():
            try:
                # Get frame from queue (timeout to check stop_event)
                try:
                    frame_data = self.frame_queue.get(timeout=0.1)
                except Empty:
                    continue
                
                camera_id = frame_data['camera_id']
                frame = frame_data['frame']
                timestamp = frame_data['timestamp']
                
                self.total_frames += 1
                
                # Process frame
                self._process_frame(camera_id, frame, timestamp)
                
                self.processed_frames += 1
                
                # Periodic cleanup
                if self.processed_frames % 1000 == 0:
                    self._periodic_cleanup()
                
            except Exception as e:
                logger.error(f"Processing error: {e}", exc_info=True)
        
        logger.info("Processing loop ended")
    
    def _process_frame(self, camera_id: int, frame: np.ndarray, timestamp: datetime):
        """Process single frame through pipeline"""
        
        # 1. Vehicle Detection
        detections = self.detector.detect(frame)
        
        if not detections:
            return
        
        # 2. Tracking
        tracker = self.trackers.get(camera_id)
        if not tracker:
            return
        
        frame_height = frame.shape[0]
        tracks = tracker.update(detections, frame_height)
        
        # 3. OCR on confirmed tracks
        ocr_engine = self.ocr_engines.get(camera_id)
        if ocr_engine:
            for track in tracks:
                if track.state.value == 'confirmed' and not track.plate_locked:
                    # Check if we should run OCR
                    if ocr_engine.can_process(track.track_id):
                        result = ocr_engine.recognize_plate(
                            frame, track.bbox, track.track_id
                        )
                        
                        if result:
                            # Add reading
                            track.add_plate_reading(
                                result['text'],
                                result['confidence']
                            )
                            
                            # Try to finalize
                            if len(track.plate_readings) >= self.config.ocr.fusion_min_samples:
                                fused = ocr_engine.fuse_readings(track.plate_readings)
                                if fused:
                                    track.finalize_plate(
                                        fused['text'],
                                        fused['confidence']
                                    )
        
        # 4. Event Detection
        event_engine = self.event_engines.get(camera_id)
        if event_engine:
            for track in tracks:
                event = event_engine.process_track(track, frame_height)
                
                if event:
                    # Log event to database
                    self.database.insert_event(event)
                    logger.info(f"Event recorded: {event['type'].upper()} - {event.get('plate_text', 'N/A')}")
    
    def _periodic_cleanup(self):
        """Periodic cleanup tasks"""
        for engine in self.event_engines.values():
            engine.cleanup_old_entries()
    
    def get_stats(self) -> Dict:
        """Get pipeline statistics"""
        uptime = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        fps = self.processed_frames / uptime if uptime > 0 else 0
        
        stats = {
            'uptime_seconds': uptime,
            'total_frames': self.total_frames,
            'processed_frames': self.processed_frames,
            'fps': fps,
            'queue_size': self.frame_queue.qsize(),
            'cameras': self.camera_manager.get_camera_stats(),
            'detector': self.detector.get_stats(),
            'database': self.database.get_stats(),
            'trackers': {
                cam_id: tracker.get_stats()
                for cam_id, tracker in self.trackers.items()
            },
            'events': {
                cam_id: engine.get_stats()
                for cam_id, engine in self.event_engines.items()
            },
            'ocr': {
                cam_id: engine.get_stats()
                for cam_id, engine in self.ocr_engines.items()
            }
        }
        
        return stats
    
    def get_latest_frame(self, camera_id: int) -> Optional[np.ndarray]:
        """Get latest processed frame with visualizations"""
        # This would be implemented with a separate visualization buffer
        # For now, returns None
        return None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def setup_logging(config: SystemConfig):
    """Configure logging"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    handlers = [logging.StreamHandler()]
    
    if config.log_file:
        handlers.append(logging.FileHandler(config.log_file))
    
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format=log_format,
        handlers=handlers
    )


def main():
    """Main entry point"""
    # Load configuration
    config = Config.load("config/config.yaml")
    
    # Setup logging
    setup_logging(config)
    
    logger.info("="*60)
    logger.info("ANPR System Starting")
    logger.info("="*60)
    logger.info(f"Mode: {config.mode.value}")
    logger.info(f"Cameras: {len(config.cameras)}")
    logger.info(f"Detection: {config.detection.model} on {config.detection.device}")
    logger.info(f"OCR: {'Enabled' if config.ocr.enabled else 'Disabled'}")
    logger.info(f"Database: {config.database.type}")
    logger.info(f"API Server: {config.api.host}:{config.api.port}")
    logger.info("="*60)
    
    # Create and start pipeline
    try:
        with ANPRPipeline(config) as pipeline:
            # Set global pipeline reference for API
            import api.server as api_server
            api_server.pipeline = pipeline
            
            # Start API server in separate thread
            import uvicorn
            from threading import Thread
            
            api_thread = Thread(
                target=lambda: uvicorn.run(
                    api_server.app,
                    host=config.api.host,
                    port=config.api.port,
                    log_level="warning"  # Reduce API logging noise
                ),
                daemon=True
            )
            api_thread.start()
            
            logger.info(f"✓ API Server started at http://{config.api.host}:{config.api.port}")
            logger.info(f"✓ Dashboard available at http://localhost:{config.api.port}/dashboard")
            logger.info("Pipeline running. Press Ctrl+C to stop.")
            
            # Keep running and log stats periodically
            while True:
                time.sleep(10)
                stats = pipeline.get_stats()
                logger.info(
                    f"Status: {stats['fps']:.1f} FPS | "
                    f"Frames: {stats['processed_frames']} | "
                    f"Queue: {stats['queue_size']}"
                )
    
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("ANPR System stopped")


if __name__ == "__main__":
    main()