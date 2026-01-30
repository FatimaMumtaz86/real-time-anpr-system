"""
Entry/Exit Event Engine
Finite State Machine for vehicle entry/exit detection
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict

from core.config import EventConfig
from core.events import (
    Track, VehicleState, EntryConfirmedEvent, ExitConfirmedEvent
)


logger = logging.getLogger(__name__)


class EventEngine:
    """Manages entry/exit event detection with deduplication"""
    
    def __init__(self, config: EventConfig, camera_id: int):
        self.config = config
        self.camera_id = camera_id
        
        # Track state history
        self.track_states: Dict[int, VehicleState] = {}
        
        # Deduplication: plate -> last event time
        self.recent_plates: Dict[str, datetime] = {}
        
        # Statistics
        self.total_entries = 0
        self.total_exits = 0
        
        logger.info(f"Event engine initialized for camera {camera_id}")
    
    def process_track(self, track: Track, frame_height: int) -> Optional[dict]:
        """
        Process track and determine if entry/exit event should be generated
        
        Args:
            track: Track object
            frame_height: Frame height for normalized positions
        
        Returns:
            Event dict or None
        """
        # Get normalized Y position of track center
        _, y1, _, y2 = track.bbox
        center_y = (y1 + y2) / 2
        normalized_y = center_y / frame_height if frame_height > 0 else 0
        
        # Get current state for this track
        current_state = self.track_states.get(track.track_id, VehicleState.OUTSIDE)
        new_state = current_state
        event = None
        
        # State machine transitions
        if current_state == VehicleState.OUTSIDE:
            # Detect entry
            if normalized_y > self.config.entry_y_threshold:
                new_state = VehicleState.APPROACHING
                logger.debug(f"Track {track.track_id} -> APPROACHING")
        
        elif current_state == VehicleState.APPROACHING:
            # Confirm entry
            dwell_time = (datetime.now() - track.first_seen).total_seconds()
            
            if dwell_time >= self.config.min_dwell_time:
                # Check if plate is required
                if self.config.require_plate_for_entry and not track.plate_locked:
                    logger.debug(f"Track {track.track_id} awaiting plate for entry")
                else:
                    # Check deduplication
                    if not self._is_duplicate_entry(track):
                        event = self._create_entry_event(track)
                        new_state = VehicleState.INSIDE
                        self.total_entries += 1
                        logger.info(
                            f"ENTRY: Track {track.track_id}, "
                            f"Plate: {track.plate_text or 'N/A'}"
                        )
        
        elif current_state == VehicleState.INSIDE:
            # Detect exit
            if normalized_y > self.config.exit_y_threshold:
                new_state = VehicleState.EXITING
                logger.debug(f"Track {track.track_id} -> EXITING")
        
        elif current_state == VehicleState.EXITING:
            # Confirm exit
            # Track is leaving frame or stopped updating
            if track.time_since_update > 5:  # Lost for 5 frames
                # Check if plate is required
                if self.config.require_plate_for_exit and not track.plate_locked:
                    logger.debug(f"Track {track.track_id} awaiting plate for exit")
                else:
                    # Check deduplication
                    if not self._is_duplicate_exit(track):
                        event = self._create_exit_event(track)
                        new_state = VehicleState.LOGGED
                        self.total_exits += 1
                        logger.info(
                            f"EXIT: Track {track.track_id}, "
                            f"Plate: {track.plate_text or 'N/A'}"
                        )
        
        # Update state
        if new_state != current_state:
            self.track_states[track.track_id] = new_state
            track.vehicle_state = new_state
        
        return event
    
    def _is_duplicate_entry(self, track: Track) -> bool:
        """Check if entry is duplicate based on plate and time"""
        if not track.plate_text:
            return False
        
        if track.plate_text in self.recent_plates:
            last_time = self.recent_plates[track.plate_text]
            elapsed = (datetime.now() - last_time).total_seconds()
            
            if elapsed < self.config.dedup_window:
                logger.debug(
                    f"Duplicate entry suppressed: {track.plate_text} "
                    f"({elapsed:.0f}s since last)"
                )
                return True
        
        return False
    
    def _is_duplicate_exit(self, track: Track) -> bool:
        """Check if exit is duplicate"""
        # Same logic as entry
        return self._is_duplicate_entry(track)
    
    def _create_entry_event(self, track: Track) -> dict:
        """Create entry event"""
        event = {
            'type': 'entry',
            'camera_id': self.camera_id,
            'track_id': track.track_id,
            'vehicle_type': track.vehicle_type.value,
            'plate_text': track.plate_text,
            'plate_confidence': track.plate_confidence,
            'timestamp': datetime.now(),
            'confidence': track.confidence,
            'metadata': {
                'color': track.color,
                'bbox': track.bbox
            }
        }
        
        # Update deduplication cache
        if track.plate_text:
            self.recent_plates[track.plate_text] = datetime.now()
        
        return event
    
    def _create_exit_event(self, track: Track) -> dict:
        """Create exit event"""
        entry_time = track.first_seen
        exit_time = datetime.now()
        duration = (exit_time - entry_time).total_seconds()
        
        event = {
            'type': 'exit',
            'camera_id': self.camera_id,
            'track_id': track.track_id,
            'vehicle_type': track.vehicle_type.value,
            'plate_text': track.plate_text,
            'plate_confidence': track.plate_confidence,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'duration': duration,
            'timestamp': exit_time,
            'confidence': track.confidence,
            'metadata': {
                'color': track.color,
                'bbox': track.bbox
            }
        }
        
        # Update deduplication cache
        if track.plate_text:
            self.recent_plates[track.plate_text] = datetime.now()
        
        return event
    
    def cleanup_old_entries(self):
        """Remove old entries from deduplication cache"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.config.dedup_window * 2)
        
        to_remove = [
            plate for plate, timestamp in self.recent_plates.items()
            if timestamp < cutoff
        ]
        
        for plate in to_remove:
            del self.recent_plates[plate]
        
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} old plate entries")
    
    def get_stats(self) -> dict:
        """Get event statistics"""
        return {
            'camera_id': self.camera_id,
            'total_entries': self.total_entries,
            'total_exits': self.total_exits,
            'active_tracks': len(self.track_states),
            'cached_plates': len(self.recent_plates)
        }