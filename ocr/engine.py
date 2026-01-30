"""
OCR Engine for License Plate Recognition
PaddleOCR-based text recognition with temporal fusion
"""

import logging
import numpy as np
import cv2
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from collections import Counter
import re

from core.config import OCRConfig


logger = logging.getLogger(__name__)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


class OCREngine:
    """License plate OCR with temporal fusion"""
    
    def __init__(self, config: OCRConfig):
        self.config = config
        self.ocr = None
        self.is_loaded = False
        
        # Track last OCR time per track to enforce throttling
        self.last_ocr_time: Dict[int, datetime] = {}
        
        # Concurrent OCR counter
        self.active_ocr_count = 0
        
        # Statistics
        self.total_ocr_calls = 0
        self.successful_reads = 0
        self.failed_reads = 0
        
        if config.enabled:
            self._load_model()
    
    def _load_model(self):
        """Load PaddleOCR model"""
        try:
            from paddleocr import PaddleOCR
            
            logger.info("Loading PaddleOCR model")
            
            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang=self.config.language,
                use_gpu=False,  # CPU mode for stability
                show_log=False
            )
            
            # Warm-up
            dummy_img = np.zeros((100, 300, 3), dtype=np.uint8)
            _ = self.ocr.ocr(dummy_img, cls=True)
            
            self.is_loaded = True
            logger.info("OCR engine ready")
            
        except Exception as e:
            logger.error(f"Failed to load OCR model: {e}")
            self.config.enabled = False
    
    def can_process(self, track_id: int) -> bool:
        """Check if OCR can be performed on track (throttling)"""
        if not self.config.enabled or not self.is_loaded:
            return False
        
        # Check concurrent limit
        if self.active_ocr_count >= self.config.max_concurrent:
            return False
        
        # Check throttling
        if track_id in self.last_ocr_time:
            elapsed = (datetime.now() - self.last_ocr_time[track_id]).total_seconds()
            min_interval = self.config.throttle_frames / 20.0  # Assume 20 FPS
            if elapsed < min_interval:
                return False
        
        return True
    
    def recognize_plate(self, frame: np.ndarray, bbox: List[float], 
                        track_id: int) -> Optional[Dict]:
        """
        Recognize license plate text
        
        Args:
            frame: Full frame
            bbox: Vehicle bounding box [x1, y1, x2, y2]
            track_id: Track ID for throttling
        
        Returns:
            Dict with 'text', 'confidence', or None
        """
        if not self.can_process(track_id):
            return None
        
        try:
            self.active_ocr_count += 1
            self.last_ocr_time[track_id] = datetime.now()
            self.total_ocr_calls += 1
            
            # Extract and preprocess ROI
            roi = self._extract_roi(frame, bbox)
            if roi is None:
                return None
            
            # Preprocess for better OCR
            roi_processed = self._preprocess_plate(roi)
            
            # Run OCR
            result = self.ocr.ocr(roi_processed, cls=True)
            
            if not result or not result[0]:
                self.failed_reads += 1
                return None
            
            # Extract text and confidence
            texts = []
            confidences = []
            
            for line in result[0]:
                if len(line) >= 2:
                    text = line[1][0]
                    conf = line[1][1]
                    texts.append(text)
                    confidences.append(conf)
            
            if not texts:
                self.failed_reads += 1
                return None
            
            # Combine multi-line results
            full_text = ' '.join(texts)
            avg_confidence = np.mean(confidences)
            
            # Clean and validate
            plate_text = self._clean_plate_text(full_text)
            
            if not plate_text or len(plate_text) < 3:
                self.failed_reads += 1
                return None
            
            self.successful_reads += 1
            
            logger.debug(f"OCR result for track {track_id}: {plate_text} ({avg_confidence:.2f})")
            
            return {
                'text': plate_text,
                'confidence': float(avg_confidence),
                'raw': full_text
            }
            
        except Exception as e:
            logger.error(f"OCR error for track {track_id}: {e}")
            self.failed_reads += 1
            return None
        
        finally:
            self.active_ocr_count -= 1
    
    def _extract_roi(self, frame: np.ndarray, bbox: List[float], 
                     expand: float = 0.1) -> Optional[np.ndarray]:
        """Extract and expand ROI from frame"""
        try:
            x1, y1, x2, y2 = map(int, bbox)
            
            # Expand bbox
            w, h = x2 - x1, y2 - y1
            x1 = max(0, int(x1 - w * expand))
            y1 = max(0, int(y1 - h * expand))
            x2 = min(frame.shape[1], int(x2 + w * expand))
            y2 = min(frame.shape[0], int(y2 + h * expand))
            
            roi = frame[y1:y2, x1:x2]
            
            if roi.size == 0:
                return None
            
            return roi
            
        except Exception as e:
            logger.error(f"ROI extraction error: {e}")
            return None
    
    def _preprocess_plate(self, roi: np.ndarray) -> np.ndarray:
        """Preprocess plate image for better OCR"""
        try:
            # Convert to grayscale
            if len(roi.shape) == 3:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            else:
                gray = roi
            
            # Resize if too small
            if gray.shape[1] < 200:
                scale = 200 / gray.shape[1]
                new_w = int(gray.shape[1] * scale)
                new_h = int(gray.shape[0] * scale)
                gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            
            # Enhance contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # Denoise
            denoised = cv2.fastNlMeansDenoising(enhanced, None, 10, 7, 21)
            
            # Threshold
            _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Convert back to BGR for PaddleOCR
            processed = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            
            return processed
            
        except Exception as e:
            logger.error(f"Preprocessing error: {e}")
            return roi
    
    @staticmethod
    def _clean_plate_text(text: str) -> str:
        """Clean and normalize plate text"""
        # Remove whitespace
        text = text.replace(' ', '').replace('-', '').replace('.', '')
        
        # Keep only alphanumeric
        text = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Common OCR mistakes
        replacements = {
            'O': '0',  # Letter O to zero
            'I': '1',  # Letter I to one
            'S': '5',  # Sometimes
            'B': '8',  # Sometimes
        }
        
        # Only apply to numeric sections
        # TODO: Implement smarter region-aware correction
        
        return text
    
    def fuse_readings(self, readings: List[Dict]) -> Optional[Dict]:
        """
        Fuse multiple OCR readings using temporal consistency
        
        Args:
            readings: List of {'text': str, 'confidence': float}
        
        Returns:
            Fused result or None
        """
        if not readings:
            return None
        
        if len(readings) < self.config.fusion_min_samples:
            # Not enough samples, return highest confidence
            return max(readings, key=lambda x: x['confidence'])
        
        # Group similar readings
        groups = []
        for reading in readings:
            text = reading['text']
            placed = False
            
            for group in groups:
                # Check if similar to group
                if levenshtein_distance(text, group[0]['text']) <= 2:
                    group.append(reading)
                    placed = True
                    break
            
            if not placed:
                groups.append([reading])
        
        # Find largest group
        largest_group = max(groups, key=len)
        
        if len(largest_group) < self.config.fusion_min_samples:
            # No consensus, return highest confidence overall
            return max(readings, key=lambda x: x['confidence'])
        
        # Return most common text in largest group with average confidence
        texts = [r['text'] for r in largest_group]
        most_common = Counter(texts).most_common(1)[0][0]
        
        avg_conf = np.mean([r['confidence'] for r in largest_group 
                           if r['text'] == most_common])
        
        return {
            'text': most_common,
            'confidence': float(avg_conf),
            'num_samples': len(largest_group)
        }
    
    def get_stats(self) -> dict:
        """Get OCR statistics"""
        success_rate = (
            self.successful_reads / self.total_ocr_calls * 100
            if self.total_ocr_calls > 0 else 0
        )
        
        return {
            'enabled': self.config.enabled,
            'total_calls': self.total_ocr_calls,
            'successful': self.successful_reads,
            'failed': self.failed_reads,
            'success_rate': f"{success_rate:.1f}%",
            'active_count': self.active_ocr_count
        }