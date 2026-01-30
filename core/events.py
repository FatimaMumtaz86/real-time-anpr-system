"""
Event Types and State Definitions
Immutable event model for inter-component communication
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid


class EventType(Enum):
    """System event types"""
    FRAME_CAPTURED = "frame_captured"
    VEHICLE_DETECTED = "vehicle_detected"
    VEHICLE_TRACKED = "vehicle_tracked"
    PLATE_DETECTED = "plate_detected"
    PLATE_RECOGNIZED = "plate_recognized"
    PLATE_FINALIZED = "plate_finalized"
    TRACK_STATE_CHANGED = "track_state_changed"
    ENTRY_CONFIRMED = "entry_confirmed"
    EXIT_CONFIRMED = "exit_confirmed"
    DB_WRITE_SUCCESS = "db_write_success"
    DB_WRITE_FAILED = "db_write_failed"
    CAMERA_CONNECTED = "camera_connected"
    CAMERA_DISCONNECTED = "camera_disconnected"
    SYSTEM_ERROR = "system_error"


class TrackState(Enum):
    """Track lifecycle states"""
    TENTATIVE = "tentative"  # Just detected, not confirmed
    CONFIRMED = "confirmed"  # Stable track
    LOST = "lost"           # Temporarily occluded
    DELETED = "deleted"     # Permanently gone


class VehicleState(Enum):
    """Vehicle position states for entry/exit logic"""
    OUTSIDE = "outside"      # Not in detection zone
    APPROACHING = "approaching"  # Detected but not crossed entry line
    INSIDE = "inside"        # Crossed entry line
    EXITING = "exiting"      # Moving toward exit
    LOGGED = "logged"        # Event recorded, tracking complete


class VehicleType(Enum):
    """Vehicle classification types"""
    CAR = "car"
    MOTORCYCLE = "motorcycle"
    BUS = "bus"
    TRUCK = "truck"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BaseEvent:
    """Base event with common metadata"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.SYSTEM_ERROR
    timestamp: datetime = field(default_factory=datetime.now)
    camera_id: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameCapturedEvent(BaseEvent):
    """Frame acquired from camera"""
    event_type: EventType = EventType.FRAME_CAPTURED
    frame_id: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class Detection:
    """Single object detection"""
    bbox: List[float]  # [x1, y1, x2, y2]
    confidence: float
    class_id: int
    class_name: str
    
    @property
    def center(self) -> tuple:
        """Get center point of bbox"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @property
    def area(self) -> float:
        """Get bbox area"""
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)


@dataclass(frozen=True)
class VehicleDetectedEvent(BaseEvent):
    """Vehicle detected in frame"""
    event_type: EventType = EventType.VEHICLE_DETECTED
    detections: List[Detection] = field(default_factory=list)
    frame_id: int = 0


@dataclass
class Track:
    """Vehicle track information (mutable for updates)"""
    track_id: int
    camera_id: int
    state: TrackState
    vehicle_type: VehicleType
    first_seen: datetime
    last_seen: datetime
    bbox: List[float]
    confidence: float
    color: Optional[str] = None
    velocity: Optional[tuple] = None  # (vx, vy)
    hits: int = 0
    age: int = 0
    time_since_update: int = 0
    
    # Plate information
    plate_readings: List[Dict[str, Any]] = field(default_factory=list)
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    plate_locked: bool = False
    
    # Entry/Exit state
    vehicle_state: VehicleState = VehicleState.OUTSIDE
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    
    def update_bbox(self, bbox: List[float], confidence: float):
        """Update track position"""
        self.bbox = bbox
        self.confidence = confidence
        self.last_seen = datetime.now()
        self.hits += 1
        self.time_since_update = 0
    
    def add_plate_reading(self, text: str, confidence: float):
        """Add OCR reading"""
        if not self.plate_locked:
            self.plate_readings.append({
                'text': text,
                'confidence': confidence,
                'timestamp': datetime.now()
            })
    
    def finalize_plate(self, text: str, confidence: float):
        """Lock plate reading"""
        self.plate_text = text
        self.plate_confidence = confidence
        self.plate_locked = True


@dataclass(frozen=True)
class VehicleTrackedEvent(BaseEvent):
    """Vehicle tracking update"""
    event_type: EventType = EventType.VEHICLE_TRACKED
    track_id: int = 0
    track_state: TrackState = TrackState.TENTATIVE
    bbox: List[float] = field(default_factory=list)
    vehicle_type: VehicleType = VehicleType.UNKNOWN
    confidence: float = 0.0


@dataclass(frozen=True)
class PlateDetectedEvent(BaseEvent):
    """License plate detected in vehicle ROI"""
    event_type: EventType = EventType.PLATE_DETECTED
    track_id: int = 0
    plate_bbox: List[float] = field(default_factory=list)  # Relative to vehicle
    confidence: float = 0.0


@dataclass(frozen=True)
class PlateRecognizedEvent(BaseEvent):
    """OCR performed on plate"""
    event_type: EventType = EventType.PLATE_RECOGNIZED
    track_id: int = 0
    plate_text: str = ""
    confidence: float = 0.0
    raw_result: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlateFinalizedEvent(BaseEvent):
    """Plate reading finalized with fusion"""
    event_type: EventType = EventType.PLATE_FINALIZED
    track_id: int = 0
    plate_text: str = ""
    confidence: float = 0.0
    num_readings: int = 0


@dataclass(frozen=True)
class TrackStateChangedEvent(BaseEvent):
    """Track state transition"""
    event_type: EventType = EventType.TRACK_STATE_CHANGED
    track_id: int = 0
    old_state: TrackState = TrackState.TENTATIVE
    new_state: TrackState = TrackState.CONFIRMED


@dataclass(frozen=True)
class EntryConfirmedEvent(BaseEvent):
    """Vehicle entry event"""
    event_type: EventType = EventType.ENTRY_CONFIRMED
    track_id: int = 0
    vehicle_type: VehicleType = VehicleType.UNKNOWN
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    entry_time: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class ExitConfirmedEvent(BaseEvent):
    """Vehicle exit event"""
    event_type: EventType = EventType.EXIT_CONFIRMED
    track_id: int = 0
    vehicle_type: VehicleType = VehicleType.UNKNOWN
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    entry_time: Optional[datetime] = None
    exit_time: datetime = field(default_factory=datetime.now)
    duration: Optional[float] = None  # seconds


@dataclass(frozen=True)
class SystemErrorEvent(BaseEvent):
    """System error or exception"""
    event_type: EventType = EventType.SYSTEM_ERROR
    component: str = ""
    error_message: str = ""
    exception_type: str = ""
    traceback: Optional[str] = None


# Event type mapping for serialization
EVENT_TYPE_MAP = {
    EventType.FRAME_CAPTURED: FrameCapturedEvent,
    EventType.VEHICLE_DETECTED: VehicleDetectedEvent,
    EventType.VEHICLE_TRACKED: VehicleTrackedEvent,
    EventType.PLATE_DETECTED: PlateDetectedEvent,
    EventType.PLATE_RECOGNIZED: PlateRecognizedEvent,
    EventType.PLATE_FINALIZED: PlateFinalizedEvent,
    EventType.TRACK_STATE_CHANGED: TrackStateChangedEvent,
    EventType.ENTRY_CONFIRMED: EntryConfirmedEvent,
    EventType.EXIT_CONFIRMED: ExitConfirmedEvent,
    EventType.SYSTEM_ERROR: SystemErrorEvent,
}