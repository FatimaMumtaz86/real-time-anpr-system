"""
ANPR System Configuration Management
Centralized configuration with validation and environment support
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class SystemMode(Enum):
    DEMO = "demo"
    PRODUCTION = "production"
    HEADLESS = "headless"


class DeviceType(Enum):
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"  # Apple Silicon


@dataclass
class CameraConfig:
    id: int
    name: str
    source: str  # USB index, RTSP URL, or file path
    fps: int = 20
    width: int = 1280
    height: int = 720
    enabled: bool = True
    
    @property
    def is_rtsp(self) -> bool:
        return self.source.startswith(("rtsp://", "http://"))
    
    @property
    def is_usb(self) -> bool:
        return self.source.isdigit()


@dataclass
class DetectionConfig:
    model: str = "yolov8n.pt"
    confidence: float = 0.4
    iou_threshold: float = 0.5
    device: str = "cpu"
    fp16: bool = False
    classes: List[int] = field(default_factory=lambda: [2, 3, 5, 7])  # car, motorcycle, bus, truck


@dataclass
class TrackingConfig:
    max_lost_frames: int = 30
    min_hits: int = 3
    iou_threshold: float = 0.3
    max_age: int = 60


@dataclass
class OCRConfig:
    enabled: bool = True
    language: str = "en"
    throttle_frames: int = 10
    min_plate_confidence: float = 0.6
    max_concurrent: int = 2
    timeout: float = 0.5
    fusion_min_samples: int = 3
    max_samples: int = 5


@dataclass
class EventConfig:
    entry_y_threshold: float = 0.6  # Normalized position
    exit_y_threshold: float = 0.9
    min_dwell_time: float = 1.0  # seconds
    dedup_window: int = 60  # seconds
    require_plate_for_entry: bool = False
    require_plate_for_exit: bool = True


@dataclass
class DatabaseConfig:
    type: str = "sqlite"
    path: str = "anpr.db"
    host: str = "localhost"
    port: int = 5432
    username: str = ""
    password: str = ""
    database: str = "anpr"
    pool_size: int = 5
    
    @property
    def connection_string(self) -> str:
        if self.type == "sqlite":
            return f"sqlite:///{self.path}"
        elif self.type == "postgresql":
            return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
        raise ValueError(f"Unsupported database type: {self.type}")


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class SystemConfig:
    mode: SystemMode = SystemMode.DEMO
    log_level: str = "INFO"
    log_file: Optional[str] = None
    frame_queue_size: int = 2
    event_buffer_size: int = 1000
    metrics_enabled: bool = True
    
    cameras: List[CameraConfig] = field(default_factory=list)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    events: EventConfig = field(default_factory=EventConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    api: APIConfig = field(default_factory=APIConfig)


class Config:
    """Global configuration singleton"""
    
    _instance: Optional['Config'] = None
    _config: Optional[SystemConfig] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def load(cls, config_path: str = "config/config.yaml") -> SystemConfig:
        """Load configuration from YAML file"""
        path = Path(config_path)
        
        if not path.exists():
            # Create default config
            cls._config = cls._create_default_config()
            cls._save_default(path)
            return cls._config
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        cls._config = cls._parse_config(data)
        return cls._config
    
    @classmethod
    def get(cls) -> SystemConfig:
        """Get current configuration"""
        if cls._config is None:
            return cls.load()
        return cls._config
    
    @classmethod
    def _create_default_config(cls) -> SystemConfig:
        """Create default configuration for demo mode"""
        return SystemConfig(
            mode=SystemMode.DEMO,
            log_level="INFO",
            cameras=[
                CameraConfig(
                    id=1,
                    name="Demo Camera",
                    source="0",  # Default USB camera
                    fps=20
                )
            ],
            detection=DetectionConfig(
                model="yolov8n.pt",
                confidence=0.4,
                device="cpu"
            ),
            tracking=TrackingConfig(),
            ocr=OCRConfig(enabled=True),
            events=EventConfig(),
            database=DatabaseConfig(
                type="sqlite",
                path="anpr.db"
            ),
            api=APIConfig(
                host="0.0.0.0",
                port=8000
            )
        )
    
    @classmethod
    def _parse_config(cls, data: Dict[str, Any]) -> SystemConfig:
        """Parse configuration dictionary into typed config"""
        
        # Parse system
        system = data.get('system', {})
        mode = SystemMode(system.get('mode', 'demo'))
        
        # Parse cameras
        cameras = [
            CameraConfig(**cam) for cam in data.get('cameras', [])
        ]
        
        # Parse other sections
        detection = DetectionConfig(**data.get('detection', {}))
        tracking = TrackingConfig(**data.get('tracking', {}))
        ocr = OCRConfig(**data.get('ocr', {}))
        events = EventConfig(**data.get('events', {}))
        database = DatabaseConfig(**data.get('database', {}))
        api = APIConfig(**data.get('api', {}))
        
        return SystemConfig(
            mode=mode,
            log_level=system.get('log_level', 'INFO'),
            log_file=system.get('log_file'),
            cameras=cameras,
            detection=detection,
            tracking=tracking,
            ocr=ocr,
            events=events,
            database=database,
            api=api
        )
    
    @classmethod
    def _save_default(cls, path: Path):
        """Save default configuration to file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        default_yaml = {
            'system': {
                'mode': 'demo',
                'log_level': 'INFO'
            },
            'cameras': [
                {
                    'id': 1,
                    'name': 'Demo Camera',
                    'source': '0',
                    'fps': 20,
                    'width': 1280,
                    'height': 720
                }
            ],
            'detection': {
                'model': 'yolov8n.pt',
                'confidence': 0.4,
                'iou_threshold': 0.5,
                'device': 'cpu',
                'fp16': False
            },
            'tracking': {
                'max_lost_frames': 30,
                'min_hits': 3,
                'iou_threshold': 0.3
            },
            'ocr': {
                'enabled': True,
                'language': 'en',
                'throttle_frames': 10,
                'min_plate_confidence': 0.6,
                'max_concurrent': 2
            },
            'events': {
                'entry_y_threshold': 0.6,
                'exit_y_threshold': 0.9,
                'min_dwell_time': 1.0,
                'dedup_window': 60,
                'require_plate_for_entry': False,
                'require_plate_for_exit': True
            },
            'database': {
                'type': 'sqlite',
                'path': 'anpr.db'
            },
            'api': {
                'host': '0.0.0.0',
                'port': 8000
            }
        }
        
        with open(path, 'w') as f:
            yaml.dump(default_yaml, f, default_flow_style=False, sort_keys=False)