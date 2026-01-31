# ANPR SYSTEM - INSTALLATION & DEPLOYMENT GUIDE

## COMPLETE PRODUCTION DEPLOYMENT GUIDE
**Target Audience:** Intern / Junior Engineer  
**Deployment Context:** Office Demo → Production

---

## TABLE OF CONTENTS

1. [System Requirements](#system-requirements)
2. [Software Prerequisites](#software-prerequisites)
3. [Installation Steps](#installation-steps)
4. [Camera Setup](#camera-setup)
5. [Running the System](#running-the-system)
6. [Testing & Verification](#testing--verification)
7. [Troubleshooting](#troubleshooting)
8. [Demo Day Checklist](#demo-day-checklist)

---

## 1. SYSTEM REQUIREMENTS

### MINIMUM HARDWARE (Demo Mode)

**CPU:** Intel Core i5 8th Gen / AMD Ryzen 5 3600 or better  
**RAM:** 8 GB  
**Storage:** 10 GB free space  
**GPU:** None (CPU-only mode)  
**Expected Performance:** 12-18 FPS

### RECOMMENDED HARDWARE (Production)

**CPU:** Intel Core i7 10th Gen / AMD Ryzen 7 5800 or better  
**RAM:** 16 GB  
**Storage:** 50 GB SSD  
**GPU:** NVIDIA GTX 1660 Ti / RTX 2060 or better (6GB VRAM minimum)  
**Expected Performance:** 30+ FPS per camera

### OPERATING SYSTEMS

**Supported:**
- Ubuntu 20.04 / 22.04 LTS (RECOMMENDED)
- Windows 10 / 11 Professional
- macOS 12+ (Apple Silicon supported, limited GPU)

**Note:** Ubuntu is strongly recommended for production deployments.

### PERFORMANCE EXPECTATIONS

| Hardware Config | FPS | Cameras | Latency |
|----------------|-----|---------|---------|
| i5 + 8GB + CPU | 15  | 1       | 150ms   |
| i7 + 16GB + CPU | 20 | 2       | 120ms   |
| i7 + RTX2060 | 35  | 4+      | 60ms    |

---

## 2. SOFTWARE PREREQUISITES

### 2.1 Python 3.11

**Why Needed:** Core runtime for the entire system

**Ubuntu Installation:**
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev
sudo apt install python3-pip
```

**Windows Installation:**
- Download from: https://www.python.org/downloads/
- **CRITICAL:** Check "Add Python to PATH" during installation
- Verify: `python --version` should show 3.11.x

**macOS Installation:**
```bash
brew install python@3.11
```

### 2.2 Git

**Why Needed:** Version control and project cloning

**Installation:**
```bash
# Ubuntu
sudo apt install git

# Windows: Download from https://git-scm.com/download/win

# macOS
brew install git
```

### 2.3 FFmpeg (For RTSP Camera Support)

**Why Needed:** Video stream decoding

**Installation:**
```bash
# Ubuntu
sudo apt install ffmpeg

# Windows: Download from https://ffmpeg.org/download.html
# Add to PATH manually

# macOS
brew install ffmpeg
```

### 2.4 GPU Support (OPTIONAL but RECOMMENDED)

**Required for GPU acceleration:**

**NVIDIA GPU Setup:**
1. **NVIDIA Driver** (Latest stable)
   - Ubuntu: `sudo apt install nvidia-driver-535`
   - Windows: Download from NVIDIA website

2. **CUDA Toolkit 11.8** (if GPU desired)
   - Download: https://developer.nvidia.com/cuda-downloads
   - Ubuntu: Follow NVIDIA's installation guide
   - Windows: Run installer

3. **cuDNN 8.9** (if GPU desired)
   - Download: https://developer.nvidia.com/cudnn (requires NVIDIA account)
   - Extract and copy to CUDA directory

**Verification:**
```bash
nvidia-smi  # Should show GPU info
nvcc --version  # Should show CUDA version
```

**Note:** If GPU setup fails, system will automatically fall back to CPU mode.

---

## 3. INSTALLATION STEPS

### Step 1: Clone Repository

```bash
cd ~/projects  # Or your preferred directory
git clone <repository-url> anpr-system
cd anpr-system
```

### Step 2: Create Virtual Environment

**Ubuntu / macOS:**
```bash
python3.11 -m venv venv
source venv/bin/activate
```

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Verification:** Your prompt should now show `(venv)`

### Step 3: Upgrade pip

```bash
python -m pip install --upgrade pip
```

### Step 4: Install Dependencies

**For CPU-only mode (Default):**
```bash
pip install -r requirements.txt
```

**For GPU mode (NVIDIA only):**
```bash
# Install PyTorch with CUDA support first
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Then install other requirements
pip install -r requirements.txt
```

**Expected Duration:** 5-10 minutes

**Common Issues:**
- If PaddleOCR fails: `pip install paddlepaddle==2.5.2 --no-deps` then retry
- If torch fails: Verify CUDA version matches PyTorch version

### Step 5: Download Models

Models are auto-downloaded on first run, but you can pre-download:

```bash
# Create models directory
mkdir -p models

# YOLOv8n will auto-download on first inference (~6 MB)
# PaddleOCR will auto-download on first use (~12 MB)
```

### Step 6: Create Configuration

```bash
# Configuration is auto-generated on first run
# To customize, edit config/config.yaml after first start
```

### Step 7: Verify Installation

```bash
python -c "import cv2; import torch; import paddleocr; print('All imports successful')"
```

Expected output: `All imports successful`

---

## 4. CAMERA SETUP

### 4.1 USB Webcam (Easiest for Demo)

**Connection:**
1. Plug USB camera into computer
2. On Linux, verify: `ls /dev/video*` shows `/dev/video0` (or similar)
3. On Windows, Camera app should detect it

**Configuration:**
Edit `config/config.yaml`:
```yaml
cameras:
  - id: 1
    name: "USB Camera"
    source: "0"  # 0 = first camera, 1 = second camera, etc.
    fps: 20
    width: 1280
    height: 720
```

**Test Command:**
```bash
python -c "import cv2; cap = cv2.VideoCapture(0); ret, frame = cap.read(); print('Camera OK' if ret else 'Camera Failed'); cap.release()"
```

### 4.2 IP Camera (RTSP)

**Prerequisites:**
- Camera must be on same network
- Know camera's IP address
- Know RTSP credentials (username/password)

**Find Camera IP:**
- Check camera documentation
- Use network scanner: `nmap -sn 192.168.1.0/24`
- Access camera web interface

**Common RTSP URL Formats:**
```
# Generic
rtsp://username:password@192.168.1.100:554/stream1

# Hikvision
rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101

# Dahua
rtsp://admin:password@192.168.1.100:554/cam/realmonitor?channel=1&subtype=0

# Axis
rtsp://root:password@192.168.1.100/axis-media/media.amp

# TP-Link
rtsp://admin:password@192.168.1.100:554/stream1
```

**Configuration:**
```yaml
cameras:
  - id: 1
    name: "Gate Camera"
    source: "rtsp://admin:password@192.168.1.100:554/stream1"
    fps: 20
```

**Test RTSP Connection:**
```bash
ffprobe rtsp://username:password@192.168.1.100:554/stream1
```

### 4.3 ONVIF Camera

**Note:** ONVIF cameras typically provide RTSP URLs. Use ONVIF Device Manager (Windows) or onvif-gui (Linux) to discover RTSP URL.

---

## 5. RUNNING THE SYSTEM

### 5.1 First Run (Demo Mode)

**Start the system:**
```bash
# Ensure virtual environment is activated
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate     # Windows

# Run
python main.py
```

**Expected Output:**
```
============================================================
ANPR System Starting
============================================================
Mode: demo
Cameras: 1
Detection: yolov8n.pt on cpu
OCR: Enabled
Database: sqlite
============================================================
[INFO] Camera Manager initialized
[INFO] Vehicle detector ready on cpu
[INFO] Tracking engine initialized for camera 1
[INFO] OCR engine ready
[INFO] Database schema created/verified
[INFO] Pipeline started successfully
[INFO] Pipeline running. Press Ctrl+C to stop.
```

**Success Indicators:**
- ✓ No error messages
- ✓ "Camera 1 connected" message appears
- ✓ FPS counter updates every 10 seconds

### 5.2 Stopping the System

**Graceful Shutdown:**
```
Press Ctrl+C
```

System will:
- Stop all cameras
- Flush database writes
- Close connections
- Exit cleanly

### 5.3 Running in Background (Linux)

```bash
# Using nohup
nohup python main.py > anpr.log 2>&1 &

# Or using screen
screen -S anpr
python main.py
# Press Ctrl+A then D to detach

# Reattach: screen -r anpr
```

---

## 6. TESTING & VERIFICATION

### 6.1 Quick System Test

**Test 1: Camera Feed**
```bash
# Run main.py and verify log shows:
# "Camera X connected: 1280x720 @ 20.0 FPS"
```

**Test 2: Vehicle Detection**
```bash
# Have someone walk or drive a vehicle in front of camera
# Check logs for:
# "Track X created: car"
```

**Test 3: License Plate Reading**
```bash
# Show a printed license plate to camera (or use real vehicle)
# Check logs for:
# "OCR result for track X: ABC1234 (0.85)"
```

**Test 4: Entry Event**
```bash
# Vehicle crosses entry threshold (60% down from top)
# Check logs for:
# "ENTRY: Track X, Plate: ABC1234"
```

**Test 5: Database Write**
```bash
# Query database to verify events recorded
sqlite3 anpr.db "SELECT * FROM events ORDER BY timestamp DESC LIMIT 5;"
```

Expected output: Recent entry/exit events

### 6.2 Performance Verification

**Check FPS:**
```bash
# Logs show FPS every 10 seconds:
# "Status: 18.5 FPS | Frames: 1850 | Queue: 0"
```

**Target FPS:**
- CPU mode: 15-20 FPS (acceptable)
- GPU mode: 30+ FPS (good)

**If FPS < 10:**
- Reduce camera resolution in config
- Enable GPU if available
- Close other programs

### 6.3 Database Query Examples

**View recent events:**
```sql
sqlite3 anpr.db
> SELECT event_type, plate_text, timestamp FROM events ORDER BY timestamp DESC LIMIT 10;
```

**Count events by type:**
```sql
> SELECT event_type, COUNT(*) FROM events GROUP BY event_type;
```

**Find vehicle by plate:**
```sql
> SELECT * FROM events WHERE plate_text = 'ABC1234';
```

---

## 7. TROUBLESHOOTING

### 7.1 Camera Issues

**Problem:** "Camera not opening" or "Frame read failed"

**Solutions:**
```bash
# Check camera device exists
ls /dev/video*  # Linux

# Try different source number
# In config.yaml, try source: "1" or "2" instead of "0"

# Check permissions (Linux)
sudo usermod -a -G video $USER
# Then logout and login

# Test with OpenCV directly
python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"
```

**Problem:** RTSP connection timeout

**Solutions:**
```bash
# Verify network connectivity
ping 192.168.1.100

# Test RTSP with ffmpeg
ffplay rtsp://username:password@192.168.1.100:554/stream1

# Check firewall (Linux)
sudo ufw allow from 192.168.1.100

# Try different RTSP URL format (see Camera Setup section)
```

### 7.2 Performance Issues

**Problem:** Low FPS (< 10)

**Solutions:**
```yaml
# 1. Reduce resolution in config.yaml
cameras:
  - width: 640  # Down from 1280
    height: 480  # Down from 720

# 2. Increase confidence threshold (fewer detections)
detection:
  confidence: 0.5  # Up from 0.4

# 3. Disable OCR temporarily
ocr:
  enabled: false
```

**Problem:** High CPU usage

**Solutions:**
- Enable GPU if available
- Reduce FPS: `fps: 15` in camera config
- Close other applications

### 7.3 OCR Issues

**Problem:** No plates detected or low accuracy

**Solutions:**
```bash
# 1. Check lighting - ensure plates are visible
# 2. Move camera closer or use higher resolution
# 3. Clean camera lens
# 4. Adjust OCR confidence threshold

# In config.yaml:
ocr:
  min_plate_confidence: 0.5  # Lower from 0.6
```

**Problem:** Incorrect plate readings

**Common Mistakes:**
- O ↔ 0 (letter O vs zero)
- I ↔ 1 (letter I vs one)
- S ↔ 5 or B ↔ 8

**Solution:** System uses temporal fusion to correct these over multiple frames.

### 7.4 Night / Low Light

**Problem:** Poor detection at night

**Solutions:**
1. Use IR illuminator
2. Increase camera exposure (camera settings)
3. Lower detection confidence threshold
4. Use camera with better low-light performance

### 7.5 Motion Blur

**Problem:** Blurry plates on fast-moving vehicles

**Solutions:**
1. Increase camera shutter speed (camera settings)
2. Use camera with global shutter
3. Add more lighting
4. Position camera perpendicular to motion

### 7.6 GPU Not Detected

**Problem:** System falls back to CPU despite having GPU

**Solutions:**
```bash
# Verify NVIDIA driver
nvidia-smi

# Verify CUDA
nvcc --version

# Reinstall PyTorch with CUDA
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Test GPU in Python
python -c "import torch; print(torch.cuda.is_available())"
```

### 7.7 Database Lock Errors

**Problem:** "Database is locked"

**Solutions:**
```bash
# Check if multiple instances running
ps aux | grep python

# Kill old instances
pkill -f main.py

# If persistent, remove lock
rm anpr.db-wal anpr.db-shm

# Restart system
```

---

## APPENDIX A: Configuration Reference

### Complete config.yaml Example

```yaml
system:
  mode: demo  # demo | production | headless
  log_level: INFO  # DEBUG | INFO | WARNING | ERROR
  log_file: null  # Optional: "anpr.log"

cameras:
  - id: 1
    name: "Main Gate"
    source: "0"  # USB: "0", RTSP: "rtsp://...", File: "video.mp4"
    fps: 20
    width: 1280
    height: 720
    enabled: true

detection:
  model: yolov8n.pt
  confidence: 0.4
  iou_threshold: 0.5
  device: cpu  # cpu | cuda
  fp16: false

tracking:
  max_lost_frames: 30
  min_hits: 3
  iou_threshold: 0.3

ocr:
  enabled: true
  language: en
  throttle_frames: 10
  min_plate_confidence: 0.6
  max_concurrent: 2
  fusion_min_samples: 3

events:
  entry_y_threshold: 0.6  # Normalized position (0-1)
  exit_y_threshold: 0.9
  min_dwell_time: 1.0  # seconds
  dedup_window: 60  # seconds
  require_plate_for_entry: false
  require_plate_for_exit: true

database:
  type: sqlite  # sqlite | postgresql
  path: anpr.db

api:
  host: 0.0.0.0
  port: 8000
```

---

## APPENDIX B: System Requirements Summary

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.11 | 3.11 |
| RAM | 8 GB | 16 GB |
| Storage | 10 GB | 50 GB SSD |
| CPU | i5 8th Gen | i7 10th Gen |
| GPU | None (CPU mode) | NVIDIA GTX 1660+ |
| OS | Ubuntu 20.04+ | Ubuntu 22.04 LTS |
| Camera | 720p USB | 1080p IP Camera |
| Network | N/A (USB) | 1 Gbps (IP cameras) |

---

## APPENDIX C: Support & Resources

**Documentation:**
- YOLOv8: https://docs.ultralytics.com/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- OpenCV: https://docs.opencv.org/

**Community:**
- Create GitHub issues for bugs
- Check logs: `tail -f anpr.log`
- Enable debug: `log_level: DEBUG`

**Performance Tuning:**
- See Architecture document for scaling strategies
- Monitor with: `htop` (CPU), `nvidia-smi` (GPU)

---

**Document Version:** 1.0  
**Last Updated:** 2026-01-30  
**Deployment Status:** PRODUCTION READY ✓

**END OF INSTALLATION GUIDE**
