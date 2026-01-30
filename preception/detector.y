"""
Vehicle Detection Module
YOLOv8-based real-time vehicle detection
"""

import logging
import numpy as np
import cv2
from typing import List, Optional, Tuple
from pathlib import Path

from core.config import DetectionConfig
from core.events import Detection, VehicleType


logger = logging.getLogger(__name__)


# YOLO class mapping (COCO dataset)
VEHICLE_CLASSES = {
    2: VehicleType.CAR,
    3: VehicleType.MOTORCYCLE,
    5: VehicleType.BUS,
    7: VehicleType.TRUCK,
}


class VehicleDetector:
    """Real-time vehicle detection using YOLO"""
    
    def __init__(self, config: DetectionConfig):
        self.config = config
        self.model = None
        self.device = config.device
        self.is_loaded = False
        
        # Performance metrics
        self.total_detections = 0
        self.total_inference_time = 0.0
        self.frame_count = 0
        
        self._load_model()
    
    def _load_model(self):
        """Load YOLO model"""
        try:
            from ultralytics import YOLO
            
            model_path = Path("models") / self.config.model
            
            if not model_path.exists():
                # Download default model
                logger.info(f"Model not found, downloading {self.config.model}")
                model_path = self.config.model
            
            logger.info(f"Loading YOLO model: {model_path}")
            self.model = YOLO(str(model_path))
            
            # Move to device
            if self.device == "cuda":
                try:
                    self.model.to('cuda')
                    logger.info("Model loaded on CUDA")
                except Exception as e:
                    logger.warning(f"CUDA not available: {e}, falling back to CPU")
                    self.device = "cpu"
            
            # Warm-up inference
            dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
            _ = self.model(dummy_img, verbose=False)
            
            self.is_loaded = True
            logger.info(f"Vehicle detector ready on {self.device}")
            
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            raise
    
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """
        Detect vehicles in frame
        
        Args:
            frame: Input frame (BGR format)
        
        Returns:
            List of Detection objects
        """
        if not self.is_loaded:
            return []
        
        try:
            # Run inference
            results = self.model(
                frame,
                conf=self.config.confidence,
                iou=self.config.iou_threshold,
                classes=self.config.classes,  # Only vehicle classes
                verbose=False,
                half=self.config.fp16
            )
            
            detections = []
            
            if len(results) > 0:
                result = results[0]
                
                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes.xyxy.cpu().numpy()  # [x1, y1, x2, y2]
                    confidences = result.boxes.conf.cpu().numpy()
                    class_ids = result.boxes.cls.cpu().numpy().astype(int)
                    
                    for box, conf, cls_id in zip(boxes, confidences, class_ids):
                        # Map to vehicle type
                        vehicle_type = VEHICLE_CLASSES.get(cls_id, VehicleType.UNKNOWN)
                        
                        detection = Detection(
                            bbox=box.tolist(),
                            confidence=float(conf),
                            class_id=int(cls_id),
                            class_name=vehicle_type.value
                        )
                        detections.append(detection)
                    
                    self.total_detections += len(detections)
            
            self.frame_count += 1
            
            return detections
            
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return []
    
    def detect_batch(self, frames: List[np.ndarray]) -> List[List[Detection]]:
        """Batch detection for efficiency"""
        if not self.is_loaded or not frames:
            return [[] for _ in frames]
        
        try:
            results = self.model(
                frames,
                conf=self.config.confidence,
                iou=self.config.iou_threshold,
                classes=self.config.classes,
                verbose=False,
                half=self.config.fp16
            )
            
            all_detections = []
            
            for result in results:
                detections = []
                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes.xyxy.cpu().numpy()
                    confidences = result.boxes.conf.cpu().numpy()
                    class_ids = result.boxes.cls.cpu().numpy().astype(int)
                    
                    for box, conf, cls_id in zip(boxes, confidences, class_ids):
                        vehicle_type = VEHICLE_CLASSES.get(cls_id, VehicleType.UNKNOWN)
                        
                        detection = Detection(
                            bbox=box.tolist(),
                            confidence=float(conf),
                            class_id=int(cls_id),
                            class_name=vehicle_type.value
                        )
                        detections.append(detection)
                
                all_detections.append(detections)
            
            return all_detections
            
        except Exception as e:
            logger.error(f"Batch detection error: {e}")
            return [[] for _ in frames]
    
    def visualize(self, frame: np.ndarray, detections: List[Detection], 
                  show_conf: bool = True) -> np.ndarray:
        """
        Draw detections on frame
        
        Args:
            frame: Input frame
            detections: List of detections
            show_conf: Show confidence scores
        
        Returns:
            Annotated frame
        """
        frame_vis = frame.copy()
        
        for det in detections:
            x1, y1, x2, y2 = map(int, det.bbox)
            
            # Color by vehicle type
            color = self._get_color(det.class_name)
            
            # Draw bounding box
            cv2.rectangle(frame_vis, (x1, y1), (x2, y2), color, 2)
            
            # Draw label
            label = det.class_name
            if show_conf:
                label += f" {det.confidence:.2f}"
            
            # Text background
            (text_width, text_height), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1
            )
            cv2.rectangle(
                frame_vis, 
                (x1, y1 - text_height - 5), 
                (x1 + text_width, y1), 
                color, 
                -1
            )
            
            # Text
            cv2.putText(
                frame_vis, 
                label, 
                (x1, y1 - 5), 
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.6, 
                (255, 255, 255), 
                1
            )
        
        return frame_vis
    
    @staticmethod
    def _get_color(class_name: str) -> Tuple[int, int, int]:
        """Get color for vehicle type"""
        colors = {
            'car': (0, 255, 0),        # Green
            'motorcycle': (255, 255, 0),  # Yellow
            'bus': (255, 0, 0),        # Red
            'truck': (0, 0, 255),      # Blue
            'unknown': (128, 128, 128)  # Gray
        }
        return colors.get(class_name, (128, 128, 128))
    
    def get_stats(self) -> dict:
        """Get detection statistics"""
        avg_detections = (
            self.total_detections / self.frame_count 
            if self.frame_count > 0 else 0
        )
        
        return {
            'total_frames': self.frame_count,
            'total_detections': self.total_detections,
            'avg_detections_per_frame': avg_detections,
            'device': self.device,
            'model': self.config.model
        }