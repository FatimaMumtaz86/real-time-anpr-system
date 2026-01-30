"""
Database Layer
Async database operations with SQLite/PostgreSQL support
"""

import logging
import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
import asyncio
from queue import Queue
from threading import Thread

from core.config import DatabaseConfig


logger = logging.getLogger(__name__)


# Database schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    location TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    vehicle_type TEXT,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    confidence REAL,
    color TEXT,
    metadata TEXT,  -- JSON
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);

CREATE TABLE IF NOT EXISTS plates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_fk INTEGER NOT NULL,
    plate_text TEXT NOT NULL,
    confidence REAL,
    num_readings INTEGER DEFAULT 1,
    locked BOOLEAN DEFAULT 0,
    finalized_at TIMESTAMP,
    FOREIGN KEY (track_fk) REFERENCES tracks(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    track_id INTEGER,
    event_type TEXT NOT NULL,  -- 'entry' or 'exit'
    vehicle_type TEXT,
    plate_text TEXT,
    plate_confidence REAL,
    timestamp TIMESTAMP NOT NULL,
    entry_time TIMESTAMP,
    exit_time TIMESTAMP,
    duration REAL,  -- seconds
    confidence REAL,
    metadata TEXT,  -- JSON
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_plate ON events(plate_text);
CREATE INDEX IF NOT EXISTS idx_events_camera ON events(camera_id);
CREATE INDEX IF NOT EXISTS idx_tracks_camera ON tracks(camera_id);
"""


class DatabaseManager:
    """Database operations manager with async writes"""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.conn: Optional[sqlite3.Connection] = None
        
        # Write queue for async operations
        self.write_queue: Queue = Queue(maxsize=1000)
        self.writer_thread: Optional[Thread] = None
        self.is_running = False
        
        # Statistics
        self.total_writes = 0
        self.failed_writes = 0
        
        self._initialize()
    
    def _initialize(self):
        """Initialize database and schema"""
        try:
            if self.config.type == "sqlite":
                # Ensure directory exists
                db_path = Path(self.config.path)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                
                self.conn = sqlite3.connect(
                    self.config.path,
                    check_same_thread=False,
                    timeout=10.0
                )
                self.conn.row_factory = sqlite3.Row
                
                # Enable WAL mode for better concurrency
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=NORMAL")
                
                logger.info(f"SQLite database initialized: {self.config.path}")
            else:
                raise NotImplementedError(f"Database type {self.config.type} not implemented")
            
            # Create schema
            self._create_schema()
            
            # Start writer thread
            self.is_running = True
            self.writer_thread = Thread(target=self._write_worker, daemon=True)
            self.writer_thread.start()
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def _create_schema(self):
        """Create database schema"""
        try:
            cursor = self.conn.cursor()
            cursor.executescript(SCHEMA_SQL)
            self.conn.commit()
            logger.info("Database schema created/verified")
        except Exception as e:
            logger.error(f"Schema creation failed: {e}")
            raise
    
    def _write_worker(self):
        """Background thread for async writes"""
        logger.info("Database writer thread started")
        
        batch = []
        last_commit = datetime.now()
        
        while self.is_running:
            try:
                # Get writes from queue (blocking with timeout)
                try:
                    write_op = self.write_queue.get(timeout=0.5)
                    batch.append(write_op)
                except:
                    pass
                
                # Commit batch if enough items or time elapsed
                should_commit = (
                    len(batch) >= 10 or
                    (datetime.now() - last_commit).total_seconds() >= 0.5
                )
                
                if batch and should_commit:
                    self._execute_batch(batch)
                    batch.clear()
                    last_commit = datetime.now()
                
            except Exception as e:
                logger.error(f"Write worker error: {e}")
        
        # Final flush
        if batch:
            self._execute_batch(batch)
        
        logger.info("Database writer thread stopped")
    
    def _execute_batch(self, batch: List[Dict]):
        """Execute batch of write operations"""
        try:
            cursor = self.conn.cursor()
            
            for op in batch:
                op_type = op['type']
                
                if op_type == 'insert_event':
                    self._insert_event(cursor, op['data'])
                elif op_type == 'insert_track':
                    self._insert_track(cursor, op['data'])
                elif op_type == 'insert_camera':
                    self._insert_camera(cursor, op['data'])
            
            self.conn.commit()
            self.total_writes += len(batch)
            
        except Exception as e:
            logger.error(f"Batch execution failed: {e}")
            self.conn.rollback()
            self.failed_writes += len(batch)
    
    def _insert_event(self, cursor, event: Dict):
        """Insert event into database"""
        metadata_json = json.dumps(event.get('metadata', {}))
        
        cursor.execute("""
            INSERT INTO events (
                camera_id, track_id, event_type, vehicle_type,
                plate_text, plate_confidence, timestamp,
                entry_time, exit_time, duration, confidence, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event['camera_id'],
            event['track_id'],
            event['type'],
            event.get('vehicle_type'),
            event.get('plate_text'),
            event.get('plate_confidence'),
            event['timestamp'],
            event.get('entry_time'),
            event.get('exit_time'),
            event.get('duration'),
            event.get('confidence'),
            metadata_json
        ))
    
    def _insert_track(self, cursor, track: Dict):
        """Insert track into database"""
        metadata_json = json.dumps(track.get('metadata', {}))
        
        cursor.execute("""
            INSERT INTO tracks (
                camera_id, track_id, vehicle_type,
                first_seen, last_seen, confidence, color, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            track['camera_id'],
            track['track_id'],
            track.get('vehicle_type'),
            track['first_seen'],
            track['last_seen'],
            track.get('confidence'),
            track.get('color'),
            metadata_json
        ))
    
    def _insert_camera(self, cursor, camera: Dict):
        """Insert or update camera"""
        cursor.execute("""
            INSERT OR REPLACE INTO cameras (id, name, source, location, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            camera['id'],
            camera['name'],
            camera['source'],
            camera.get('location', ''),
            camera.get('status', 'active')
        ))
    
    # Public API methods (async via queue)
    
    def insert_event(self, event: Dict):
        """Queue event for insertion"""
        try:
            self.write_queue.put_nowait({
                'type': 'insert_event',
                'data': event
            })
        except:
            logger.warning("Write queue full, dropping event")
    
    def insert_track(self, track: Dict):
        """Queue track for insertion"""
        try:
            self.write_queue.put_nowait({
                'type': 'insert_track',
                'data': track
            })
        except:
            logger.warning("Write queue full, dropping track")
    
    def insert_camera(self, camera: Dict):
        """Queue camera for insertion"""
        try:
            self.write_queue.put_nowait({
                'type': 'insert_camera',
                'data': camera
            })
        except:
            logger.warning("Write queue full, dropping camera")
    
    # Query methods (synchronous reads)
    
    def get_recent_events(self, limit: int = 100, camera_id: Optional[int] = None) -> List[Dict]:
        """Get recent events"""
        try:
            query = """
                SELECT * FROM events
                WHERE 1=1
            """
            params = []
            
            if camera_id is not None:
                query += " AND camera_id = ?"
                params.append(camera_id)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            
            events = []
            for row in cursor.fetchall():
                event = dict(row)
                if event['metadata']:
                    event['metadata'] = json.loads(event['metadata'])
                events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []
    
    def get_events_by_plate(self, plate_text: str, limit: int = 10) -> List[Dict]:
        """Get events for specific plate"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM events
                WHERE plate_text = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (plate_text, limit))
            
            events = []
            for row in cursor.fetchall():
                event = dict(row)
                if event['metadata']:
                    event['metadata'] = json.loads(event['metadata'])
                events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Get database statistics"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM events")
            total_events = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'entry'")
            total_entries = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'exit'")
            total_exits = cursor.fetchone()[0]
            
            return {
                'total_events': total_events,
                'total_entries': total_entries,
                'total_exits': total_exits,
                'total_writes': self.total_writes,
                'failed_writes': self.failed_writes,
                'queue_size': self.write_queue.qsize()
            }
            
        except Exception as e:
            logger.error(f"Stats query failed: {e}")
            return {}
    
    def close(self):
        """Close database connection"""
        logger.info("Closing database")
        
        # Stop writer thread
        self.is_running = False
        if self.writer_thread:
            self.writer_thread.join(timeout=5.0)
        
        # Close connection
        if self.conn:
            self.conn.close()
        
        logger.info("Database closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()