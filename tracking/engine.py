"""
Vehicle Tracking Engine
ByteTrack-based multi-object tracking with lifecycle management
"""

import logging
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from core.config import TrackingConfig
from core.events import Detection, Track, TrackState, VehicleType, VehicleState


logger = logging.getLogger(__name__)


def iou(bbox1: List[float], bbox2: List[float]) -> float:
    """Calculate Intersection over Union"""
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    
    # Intersection
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i < x1_i or y2_i < y1_i:
        return 0.0
    
    intersection = (x2_i - x1_i) * (y2_i - y1_i)
    
    # Union
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0.0


class KalmanFilter:
    """Simple Kalman filter for bbox tracking"""
    
    def __init__(self, bbox: List[float]):
        # State: [x, y, w, h, vx, vy, vw, vh]
        x1, y1, x2, y2 = bbox
        self.state = np.array([
            (x1 + x2) / 2,  # center x
            (y1 + y2) / 2,  # center y
            x2 - x1,        # width
            y2 - y1,        # height
            0, 0, 0, 0      # velocities
        ])
        
        # Covariance matrix
        self.P = np.eye(8) * 10
        
        # State transition matrix
        self.F = np.eye(8)
        self.F[0, 4] = 1  # x += vx
        self.F[1, 5] = 1  # y += vy
        self.F[2, 6] = 1  # w += vw
        self.F[3, 7] = 1  # h += vh
        
        # Measurement matrix
        self.H = np.eye(4, 8)
        
        # Process noise
        self.Q = np.eye(8) * 0.1
        
        # Measurement noise
        self.R = np.eye(4) * 1
    
    def predict(self) -> List[float]:
        """Predict next state"""
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        
        return self.get_bbox()
    
    def update(self, bbox: List[float]):
        """Update with measurement"""
        x1, y1, x2, y2 = bbox
        measurement = np.array([
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            x2 - x1,
            y2 - y1
        ])
        
        y = measurement - (self.H @ self.state)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        
        self.state = self.state + K @ y
        self.P = (np.eye(8) - K @ self.H) @ self.P
    
    def get_bbox(self) -> List[float]:
        """Get bbox from state"""
        cx, cy, w, h = self.state[:4]
        return [
            cx - w/2,
            cy - h/2,
            cx + w/2,
            cy + h/2
        ]
    
    def get_velocity(self) -> tuple:
        """Get velocity"""
        return (self.state[4], self.state[5])


class TrackingEngine:
    """Multi-object tracking with ByteTrack algorithm"""
    
    def __init__(self, config: TrackingConfig, camera_id: int):
        self.config = config
        self.camera_id = camera_id
        
        self.tracks: Dict[int, Track] = {}
        self.next_track_id = 1
        
        self.kalman_filters: Dict[int, KalmanFilter] = {}
        
        # Statistics
        self.total_tracks = 0
        self.active_tracks = 0
        
        logger.info(f"Tracking engine initialized for camera {camera_id}")
    
    def update(self, detections: List[Detection], frame_height: int) -> List[Track]:
        """
        Update tracks with new detections
        
        Args:
            detections: List of detections from current frame
            frame_height: Frame height for normalized positions
        
        Returns:
            List of active tracks
        """
        # Predict all tracks
        for track_id, kf in self.kalman_filters.items():
            predicted_bbox = kf.predict()
            if track_id in self.tracks:
                self.tracks[track_id].bbox = predicted_bbox
                self.tracks[track_id].age += 1
                self.tracks[track_id].time_since_update += 1
        
        # Match detections to tracks
        matched, unmatched_dets, unmatched_tracks = self._match(detections)
        
        # Update matched tracks
        for track_id, det_idx in matched:
            detection = detections[det_idx]
            track = self.tracks[track_id]
            
            # Update Kalman filter
            self.kalman_filters[track_id].update(detection.bbox)
            
            # Update track
            track.update_bbox(
                self.kalman_filters[track_id].get_bbox(),
                detection.confidence
            )
            track.vehicle_type = VehicleType(detection.class_name)
            
            # Update velocity
            track.velocity = self.kalman_filters[track_id].get_velocity()
            
            # State transition: TENTATIVE → CONFIRMED
            if track.state == TrackState.TENTATIVE and track.hits >= self.config.min_hits:
                track.state = TrackState.CONFIRMED
                logger.debug(f"Track {track_id} confirmed")
            
            # State transition: LOST → CONFIRMED
            if track.state == TrackState.LOST:
                track.state = TrackState.CONFIRMED
                logger.debug(f"Track {track_id} recovered")
        
        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            detection = detections[det_idx]
            self._create_track(detection, frame_height)
        
        # Handle unmatched tracks (lost)
        for track_id in unmatched_tracks:
            track = self.tracks[track_id]
            
            if track.state == TrackState.CONFIRMED:
                track.state = TrackState.LOST
            
            # Delete tracks that are lost too long
            if track.time_since_update > self.config.max_lost_frames:
                track.state = TrackState.DELETED
                logger.debug(f"Track {track_id} deleted")
        
        # Remove deleted tracks
        deleted_ids = [
            tid for tid, track in self.tracks.items()
            if track.state == TrackState.DELETED
        ]
        for tid in deleted_ids:
            del self.tracks[tid]
            del self.kalman_filters[tid]
        
        # Return active tracks
        active = [
            track for track in self.tracks.values()
            if track.state in [TrackState.CONFIRMED, TrackState.LOST]
        ]
        
        self.active_tracks = len(active)
        
        return active
    
    def _match(self, detections: List[Detection]) -> tuple:
        """Match detections to tracks using IoU"""
        if not self.tracks or not detections:
            unmatched_dets = list(range(len(detections)))
            unmatched_tracks = list(self.tracks.keys())
            return [], unmatched_dets, unmatched_tracks
        
        # Compute IoU matrix
        track_ids = list(self.tracks.keys())
        iou_matrix = np.zeros((len(track_ids), len(detections)))
        
        for i, track_id in enumerate(track_ids):
            track = self.tracks[track_id]
            for j, detection in enumerate(detections):
                iou_matrix[i, j] = iou(track.bbox, detection.bbox)
        
        # Greedy matching
        matched = []
        unmatched_dets = set(range(len(detections)))
        unmatched_tracks = set(track_ids)
        
        # Sort by IoU (highest first)
        matches = []
        for i in range(len(track_ids)):
            for j in range(len(detections)):
                if iou_matrix[i, j] > self.config.iou_threshold:
                    matches.append((i, j, iou_matrix[i, j]))
        
        matches.sort(key=lambda x: x[2], reverse=True)
        
        for i, j, _ in matches:
            track_id = track_ids[i]
            if track_id in unmatched_tracks and j in unmatched_dets:
                matched.append((track_id, j))
                unmatched_tracks.discard(track_id)
                unmatched_dets.discard(j)
        
        return matched, list(unmatched_dets), list(unmatched_tracks)
    
    def _create_track(self, detection: Detection, frame_height: int):
        """Create new track from detection"""
        track_id = self.next_track_id
        self.next_track_id += 1
        
        now = datetime.now()
        
        track = Track(
            track_id=track_id,
            camera_id=self.camera_id,
            state=TrackState.TENTATIVE,
            vehicle_type=VehicleType(detection.class_name),
            first_seen=now,
            last_seen=now,
            bbox=detection.bbox,
            confidence=detection.confidence,
            hits=1,
            age=0,
            time_since_update=0
        )
        
        self.tracks[track_id] = track
        self.kalman_filters[track_id] = KalmanFilter(detection.bbox)
        
        self.total_tracks += 1
        
        logger.debug(f"Track {track_id} created: {detection.class_name}")
    
    def get_track(self, track_id: int) -> Optional[Track]:
        """Get track by ID"""
        return self.tracks.get(track_id)
    
    def get_all_tracks(self) -> List[Track]:
        """Get all active tracks"""
        return list(self.tracks.values())
    
    def get_confirmed_tracks(self) -> List[Track]:
        """Get only confirmed tracks"""
        return [
            track for track in self.tracks.values()
            if track.state == TrackState.CONFIRMED
        ]
    
    def get_stats(self) -> dict:
        """Get tracking statistics"""
        return {
            'camera_id': self.camera_id,
            'active_tracks': self.active_tracks,
            'total_tracks': self.total_tracks,
            'tentative': sum(1 for t in self.tracks.values() if t.state == TrackState.TENTATIVE),
            'confirmed': sum(1 for t in self.tracks.values() if t.state == TrackState.CONFIRMED),
            'lost': sum(1 for t in self.tracks.values() if t.state == TrackState.LOST)
        }