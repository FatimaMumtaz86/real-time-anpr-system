# REAL-TIME VEHICLE DETECTION & ANPR SYSTEM
## FINAL PRODUCTION ARCHITECTURE

**Version:** 1.0 LOCKED  
**Target:** Office Demo → Production Deployment  
**Classification:** Industrial Grade  

---

## 1. EXECUTIVE SUMMARY

This system provides real-time vehicle detection, tracking, and license plate recognition suitable for:
- Parking management systems
- Toll plaza monitoring
- Safe City surveillance
- Access control gates

**Design Philosophy:** Event-driven, fault-isolated, scalable from single-camera demos to multi-site deployments.

---

## 2. FINAL TECHNOLOGY STACK

### Core Runtime
- **Language:** Python 3.11
- **Concurrency:** asyncio + threading for I/O and compute separation

### Computer Vision Stack
- **Detection:** YOLOv8n (ultralytics) - optimized for speed
- **Tracking:** ByteTrack - production-grade multi-object tracking
- **OCR:** PaddleOCR - best offline plate recognition
- **Backend:** OpenCV for camera I/O

### Data & API Layer
- **Database:** SQLite (demo) / PostgreSQL (production)
- **API:** FastAPI with async support
- **UI:** React + WebSocket for live streaming

### Hardware Targets
- **Minimum:** Intel i5 8th gen, 8GB RAM, CPU-only
- **Recommended:** NVIDIA GPU (GTX 1660+), 16GB RAM
- **Expected FPS:** 15-20 (CPU) / 30+ (GPU)

---

## 3. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                     CAMERA LAYER                            │
│  USB / RTSP / ONVIF (Multi-camera ready)                    │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────▼──────────┐
         │  Camera Manager      │  • Connection pool
         │  (Async I/O)         │  • Auto-reconnect
         └───────────┬──────────┘  • Frame buffering
                     │
         ┌───────────▼──────────┐
         │  Frame Pipeline      │  • Inference queue
         │  (ThreadPool)        │  • GPU batching
         └───────────┬──────────┘  • Frame dropping
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼────┐    ┌──────▼─────┐   ┌────▼─────┐
│Vehicle │    │  Tracking  │   │   OCR    │
│Detector│───▶│   Engine   │──▶│  Engine  │
└────────┘    └──────┬─────┘   └────┬─────┘
                     │                │
              ┌──────▼────────────────▼─────┐
              │   Event State Machine       │
              │   • Entry/Exit logic        │
              │   • Deduplication           │
              │   • Confidence fusion       │
              └──────┬──────────────────────┘
                     │
         ┌───────────▼──────────┐
         │  Persistence Layer   │  • Event log
         │  (Async writes)      │  • Transaction safety
         └───────────┬──────────┘  • Query optimization
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼────┐    ┌──────▼─────┐   ┌────▼─────┐
│REST API│    │ WebSocket  │   │Dashboard │
└────────┘    └────────────┘   └──────────┘
```

---

## 4. COMPONENT SPECIFICATIONS

### 4.1 Camera Manager
**Responsibility:** Reliable frame acquisition from multiple sources

**Features:**
- Asynchronous connection handling
- Automatic reconnection with exponential backoff
- Frame rate adaptation
- Health monitoring

**Failure Modes:**
- Camera disconnect → reconnect loop
- Network timeout → fallback to last frame
- Format error → skip frame

### 4.2 Detection Pipeline
**Model:** YOLOv8n (nano) for real-time performance

**Classes:** car, motorcycle, bus, truck

**Processing:**
- Inference: ~20-30ms (GPU) / ~80-100ms (CPU)
- Confidence threshold: 0.4
- NMS threshold: 0.5

**Output:** Bounding boxes with class, confidence, coordinates

### 4.3 Tracking Engine
**Algorithm:** ByteTrack with Kalman filtering

**State Machine:**
```
TENTATIVE → CONFIRMED → LOST → DELETED
```

**Parameters:**
- Track initialization: 3 consecutive frames
- Lost track timeout: 30 frames (~1.5s)
- Occlusion handling: position prediction

**Output:** Persistent track IDs, trajectories, state

### 4.4 OCR Engine
**Model:** PaddleOCR (English + Numbers optimized)

**Trigger Logic:**
- Only on CONFIRMED tracks
- Plate confidence > 0.6
- Maximum 1 OCR per 10 frames per track
- ROI expansion: 10% padding

**Fusion Strategy:**
- Collect up to 5 readings per track
- Levenshtein distance < 2 for grouping
- Select most frequent reading
- Lock when 3+ identical readings

**Output:** Plate text, confidence, locked status

### 4.5 Event State Machine

**States:**
```
OUTSIDE → APPROACHING → INSIDE → EXITING → LOGGED
```

**Entry Event Criteria:**
- Track crosses virtual line (y > threshold)
- Direction: top → bottom
- Minimum dwell: 1 second
- Plate finalized (optional for entry, required for exit)

**Exit Event Criteria:**
- Track leaves frame or crosses exit line
- Minimum time inside: 2 seconds
- Final plate reading available

**Deduplication:**
- Same plate within 60 seconds → ignored
- Track ID prevents double-counting

### 4.6 Persistence Layer

**Database Schema:**
```sql
cameras (
  id INTEGER PRIMARY KEY,
  name TEXT,
  rtsp_url TEXT,
  location TEXT,
  status TEXT
)

tracks (
  id INTEGER PRIMARY KEY,
  camera_id INTEGER,
  track_id INTEGER,
  first_seen TIMESTAMP,
  last_seen TIMESTAMP,
  vehicle_type TEXT,
  color TEXT,
  confidence REAL
)

plates (
  id INTEGER PRIMARY KEY,
  track_id INTEGER,
  plate_text TEXT,
  confidence REAL,
  locked BOOLEAN,
  finalized_at TIMESTAMP
)

events (
  id INTEGER PRIMARY KEY,
  camera_id INTEGER,
  track_id INTEGER,
  event_type TEXT,  -- ENTRY / EXIT
  plate_text TEXT,
  timestamp TIMESTAMP,
  metadata JSON
)
```

**Write Strategy:**
- Async batch writes every 500ms
- Connection pooling
- Transaction rollback on error
- Write-ahead logging for recovery

---

## 5. DATA FLOW (END-TO-END)

```
1. Camera Manager acquires frame
   ↓
2. Frame pushed to inference queue (size: 2)
   ↓
3. YOLO detection runs (async ThreadPoolExecutor)
   ↓
4. Detections → Tracker updates
   ↓
5. For CONFIRMED tracks:
   a. Extract plate ROI
   b. OCR inference (throttled)
   c. Update plate readings
   ↓
6. Event FSM evaluates track state
   ↓
7. On state transition:
   a. Create event object
   b. Queue for DB write
   c. Emit to WebSocket clients
   ↓
8. DB writer commits batch asynchronously
   ↓
9. Dashboard receives live update
```

**Critical Path Timing:**
- Frame → Detection: 80-100ms
- Detection → Tracking: <5ms
- OCR (when triggered): 100-150ms
- Event creation: <1ms
- DB write (async): non-blocking

**Total Latency:** 100-200ms per frame

---

## 6. PERFORMANCE SAFEGUARDS

### Frame Drop Policy
- Queue full → drop oldest frame
- Max queue depth: 2 frames
- Metric: dropped_frames counter

### OCR Throttling
- Per-track cooldown: 10 frames
- Max concurrent OCR: 2
- Timeout: 500ms → skip

### Memory Management
- Track history: last 100 frames
- Event buffer: 1000 events
- Database connection pool: 5 connections

### GPU Memory
- Batch size: 1 (real-time priority)
- Model precision: FP16 on supported GPUs
- Fallback: CPU inference automatically

---

## 7. FAULT TOLERANCE

### Camera Failures
- **Symptom:** Connection lost
- **Action:** Log error, retry every 5s
- **UI:** Show "Camera Offline" status

### Detection Failures
- **Symptom:** Exception in inference
- **Action:** Skip frame, log error
- **Fallback:** Continue with tracking only

### OCR Failures
- **Symptom:** Timeout or poor quality
- **Action:** Mark reading as invalid
- **Fallback:** Use next frame's attempt

### Database Failures
- **Symptom:** Write error
- **Action:** Queue in memory buffer
- **Recovery:** Retry on next cycle
- **Limit:** Max 10,000 events in memory

---

## 8. OPERATIONAL MODES

### Demo Mode (Default)
- Single USB camera
- SQLite database
- CPU inference
- Local web UI on :8000

### Production Mode
- Multiple RTSP cameras
- PostgreSQL database
- GPU inference
- Reverse proxy deployment

### Headless Mode
- API only
- No UI rendering
- Metrics export to Prometheus

---

## 9. CONFIGURATION

**File:** `config.yaml`

```yaml
system:
  mode: demo  # demo | production
  log_level: INFO
  
cameras:
  - id: 1
    name: "Main Gate"
    source: "0"  # USB camera index
    fps: 20
    
detection:
  model: yolov8n
  confidence: 0.4
  device: cpu  # cpu | cuda
  
tracking:
  max_lost_frames: 30
  min_hits: 3
  
ocr:
  enabled: true
  language: en
  throttle_frames: 10
  
events:
  entry_y_threshold: 0.6
  min_dwell_time: 1.0
  dedup_window: 60
  
database:
  type: sqlite  # sqlite | postgresql
  path: anpr.db
  
api:
  host: 0.0.0.0
  port: 8000
```

---

## 10. DEPLOYMENT ARCHITECTURE

### Single Machine (Demo)
```
┌─────────────────────────────┐
│  Ubuntu 22.04 / Windows 11  │
│  Python 3.11                │
│  8GB RAM                    │
│                             │
│  ┌────────────────────┐     │
│  │  ANPR Service      │     │
│  │  (main.py)         │     │
│  └────────────────────┘     │
│                             │
│  ┌────────────────────┐     │
│  │  SQLite DB         │     │
│  └────────────────────┘     │
│                             │
│  ┌────────────────────┐     │
│  │  FastAPI + React   │     │
│  │  :8000             │     │
│  └────────────────────┘     │
└─────────────────────────────┘
```

### Multi-Camera Production
```
┌──────────────────────────────────────────┐
│  Camera Ingest Nodes (N cameras)         │
│  ┌────────┐  ┌────────┐  ┌────────┐     │
│  │Camera 1│  │Camera 2│  │Camera N│     │
│  └───┬────┘  └───┬────┘  └───┬────┘     │
└──────┼───────────┼───────────┼──────────┘
       │           │           │
       └───────────┼───────────┘
                   │
         ┌─────────▼──────────┐
         │  Processing Cluster │
         │  (GPU workers)      │
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  PostgreSQL         │
         │  (replicated)       │
         └─────────┬──────────┘
                   │
         ┌─────────▼──────────┐
         │  API Gateway        │
         │  + Dashboard        │
         └────────────────────┘
```

---

## 11. CRITICAL DESIGN DECISIONS

### Why This Architecture Wins

**1. Event-Driven Design**
- Clean separation of concerns
- Easy to add new features (analytics, alerts)
- Testable in isolation

**2. Async I/O + Threaded Compute**
- Camera I/O doesn't block inference
- GPU utilization maximized
- Graceful degradation under load

**3. State Machine for Events**
- Eliminates race conditions
- Predictable behavior
- Audit trail for every decision

**4. Offline-First**
- No cloud dependencies
- Low latency
- Data sovereignty

**5. Modular Components**
- Swap YOLO → other detector
- Swap PaddleOCR → Tesseract
- Swap SQLite → PostgreSQL
- No architecture changes needed

### What Makes This Production-Grade

- **Fault isolation:** Component crash doesn't kill system
- **Observability:** Structured logging + metrics
- **Configurability:** Zero code changes for deployment
- **Performance:** 20 FPS on modest hardware
- **Scalability:** Horizontal camera addition
- **Maintainability:** Clear module boundaries

---

## 12. KNOWN LIMITATIONS & MITIGATIONS

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Night/low light | Poor detection | IR camera, exposure tuning |
| Motion blur | OCR failures | Higher shutter speed, multi-frame fusion |
| Occlusion | Lost tracks | Kalman prediction, re-identification |
| Dirty plates | OCR errors | Preprocessing, confidence thresholds |
| U-turns | False entry/exit | Direction validation, dwell time |
| CPU inference | Low FPS | GPU upgrade, model pruning |

---

## 13. SUCCESS CRITERIA

### Demo Day Requirements
✓ Camera connects and streams  
✓ Vehicles detected in real-time  
✓ Plates recognized (>80% accuracy on clean plates)  
✓ Entry/Exit events logged correctly  
✓ Dashboard shows live feed + metadata  
✓ Database query returns recent events  

### Production Requirements
✓ 99.9% uptime over 30 days  
✓ <200ms end-to-end latency  
✓ Handle 4+ cameras simultaneously  
✓ Automatic recovery from failures  
✓ Complete audit trail  

---

## 14. FUTURE ENHANCEMENTS (POST-DEMO)

**Phase 2:**
- Vehicle re-identification across cameras
- Speed estimation
- Alert system (blacklist, whitelist)
- Mobile app integration

**Phase 3:**
- Edge TPU support (Coral)
- Kubernetes deployment
- Multi-region replication
- ML model retraining pipeline

---

**STATUS:** ARCHITECTURE LOCKED ✓  
**NEXT:** Full implementation in code
