import base64
import cv2
import numpy as np
import pyzbar.pyzbar as pyzbar
from typing import List, Dict, Any, Tuple

def decode_base64_image(base64_str: str) -> np.ndarray:
    """Decodes a base64 data URI string (from HTML5 canvas) into an OpenCV BGR image."""
    if ',' in base64_str:
        base64_str = base64_str.split(',', 1)[1]
    image_bytes = base64.b64decode(base64_str)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return image

def preprocess_for_low_light(gray_img: np.ndarray) -> List[np.ndarray]:
    """
    Generates multiple enhanced variations of the image for robust detection:
    1. Standard grayscale
    2. CLAHE (Contrast Limited Adaptive Histogram Equalization) for low/uneven lighting
    3. Sharpened CLAHE
    4. Otsu / Adaptive threshold
    """
    variants = [gray_img]
    
    try:
        # 1. CLAHE enhancement
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        clahe_img = clahe.apply(gray_img)
        variants.append(clahe_img)
        
        # 2. Sharpened CLAHE (helps moving or slightly blurry cards)
        kernel = np.array([[-1, -1, -1],
                           [-1,  9, -1],
                           [-1, -1, -1]])
        sharpened = cv2.filter2D(clahe_img, -1, kernel)
        variants.append(sharpened)
        
        # 3. Adaptive threshold
        thresh = cv2.adaptiveThreshold(
            gray_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
        )
        variants.append(thresh)
    except Exception:
        pass
        
    return variants

def scan_barcodes_from_image(image: np.ndarray) -> List[Dict[str, Any]]:
    """
    Detects and decodes barcodes from an OpenCV image.
    Tries standard and enhanced pipelines to ensure detection in low light and moving cards.
    """
    if image is None or image.size == 0:
        return []
        
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Try multiple image enhancement passes
    image_variants = preprocess_for_low_light(gray)
    
    detected = []
    seen_codes = set()
    
    for variant in image_variants:
        decoded_objects = pyzbar.decode(variant)
        for obj in decoded_objects:
            try:
                data_str = obj.data.decode('utf-8').strip()
            except UnicodeDecodeError:
                data_str = obj.data.decode('latin-1', errors='ignore').strip()
                
            if not data_str or data_str in seen_codes:
                continue
                
            seen_codes.add(data_str)
            
            # Extract polygon points
            polygon = [{"x": int(pt.x), "y": int(pt.y)} for pt in obj.polygon]
            
            # Extract bounding rectangle
            rect = {
                "x": int(obj.rect.left),
                "y": int(obj.rect.top),
                "w": int(obj.rect.width),
                "h": int(obj.rect.height)
            }
            
            detected.append({
                "data": data_str,
                "type": obj.type,
                "rect": rect,
                "polygon": polygon
            })
            
        if detected:
            # If detected in this pass, return immediately for maximum speed
            break
            
    return detected

def annotate_image_with_barcodes(image: np.ndarray, barcodes: List[Dict[str, Any]]) -> np.ndarray:
    """
    Draws bounding box polygons and corner accents over detected barcodes using OpenCV.
    """
    annotated = image.copy()
    
    for b in barcodes:
        pts = b.get('polygon', [])
        if pts and len(pts) >= 4:
            pts_array = np.array([[p['x'], p['y']] for p in pts], np.int32)
            pts_array = pts_array.reshape((-1, 1, 2))
            
            # Draw glowing green polygon
            cv2.polylines(annotated, [pts_array], isClosed=True, color=(0, 255, 128), thickness=3)
            
            # Draw corner accents
            for p in pts:
                cv2.circle(annotated, (p['x'], p['y']), 5, (0, 255, 255), -1)
        else:
            # Fallback to rect
            r = b.get('rect', {})
            x, y, w, h = r.get('x', 0), r.get('y', 0), r.get('w', 0), r.get('h', 0)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 128), 3)
            
        # Draw label text background
        label = f"{b['type']}: {b['data']}"
        pos_y = max(25, b.get('rect', {}).get('y', 30) - 10)
        pos_x = b.get('rect', {}).get('x', 10)
        
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(annotated, (pos_x, pos_y - h - 5), (pos_x + w + 10, pos_y + 5), (0, 0, 0), -1)
        cv2.putText(annotated, label, (pos_x + 5, pos_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 128), 2)
        
    return annotated
