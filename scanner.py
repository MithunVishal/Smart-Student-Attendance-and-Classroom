import base64
import cv2
import numpy as np
import pyzbar.pyzbar as pyzbar
from typing import List, Dict, Any, Tuple

try:
    import zxingcpp
    HAS_ZXING = True
except ImportError:
    HAS_ZXING = False

def decode_base64_image(base64_str: str) -> np.ndarray:
    """Decodes a base64 data URI string (from HTML5 canvas or upload) into an OpenCV BGR image."""
    if ',' in base64_str:
        base64_str = base64_str.split(',', 1)[1]
    image_bytes = base64.b64decode(base64_str)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return image

def preprocess_for_low_light(gray_img: np.ndarray) -> List[np.ndarray]:
    """
    Generates enhanced variations of the image for robust detection:
    1. Standard grayscale
    2. CLAHE (Contrast Limited Adaptive Histogram Equalization) for low/uneven lighting
    3. Sharpened CLAHE
    4. Adaptive threshold
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
    Uses multi-stage enhancement combining Pyzbar and ZXing-cpp for maximum real-world detection accuracy.
    """
    if image is None or image.size == 0:
        return []
        
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image_variants = preprocess_for_low_light(gray)
    
    detected = []
    seen_codes = set()
    
    # Pass 1: Try Pyzbar across enhanced variations
    for variant in image_variants:
        try:
            decoded_objects = pyzbar.decode(variant)
            for obj in decoded_objects:
                try:
                    data_str = obj.data.decode('utf-8').strip()
                except UnicodeDecodeError:
                    data_str = obj.data.decode('latin-1', errors='ignore').strip()
                    
                if not data_str or data_str in seen_codes:
                    continue
                    
                seen_codes.add(data_str)
                polygon = [{"x": int(pt.x), "y": int(pt.y)} for pt in obj.polygon]
                rect = {
                    "x": int(obj.rect.left),
                    "y": int(obj.rect.top),
                    "w": int(obj.rect.width),
                    "h": int(obj.rect.height)
                }
                
                detected.append({
                    "data": data_str,
                    "type": str(obj.type),
                    "rect": rect,
                    "polygon": polygon
                })
        except Exception:
            pass
            
        if detected:
            return detected

    # Pass 2: Try ZXing-cpp (exceptional with skewed, tilted, or low-contrast ID card barcodes)
    if HAS_ZXING and not detected:
        for variant in [image, gray] + image_variants:
            try:
                z_objects = zxingcpp.read_barcodes(variant)
                for z_obj in z_objects:
                    data_str = z_obj.text.strip()
                    if not data_str or data_str in seen_codes:
                        continue
                        
                    seen_codes.add(data_str)
                    
                    pos = z_obj.position
                    polygon = [
                        {"x": int(pos.top_left.x), "y": int(pos.top_left.y)},
                        {"x": int(pos.top_right.x), "y": int(pos.top_right.y)},
                        {"x": int(pos.bottom_right.x), "y": int(pos.bottom_right.y)},
                        {"x": int(pos.bottom_left.x), "y": int(pos.bottom_left.y)}
                    ]
                    
                    xs = [p['x'] for p in polygon]
                    ys = [p['y'] for p in polygon]
                    rect = {
                        "x": min(xs),
                        "y": min(ys),
                        "w": max(xs) - min(xs),
                        "h": max(ys) - min(ys)
                    }
                    
                    detected.append({
                        "data": data_str,
                        "type": z_obj.format.name,
                        "rect": rect,
                        "polygon": polygon
                    })
            except Exception:
                pass
                
            if detected:
                return detected
                
    return detected

def decode_barcode_from_file_bytes(file_bytes: bytes) -> Dict[str, Any]:
    """
    Decodes barcode from raw uploaded file bytes.
    Returns {'success': True, 'barcode_id': ..., 'type': ...} or {'success': False, 'message': ...}
    """
    try:
        np_arr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            return {'success': False, 'message': 'Could not decode image file'}
            
        barcodes = scan_barcodes_from_image(img)
        if barcodes:
            return {
                'success': True,
                'barcode_id': barcodes[0]['data'],
                'barcode_type': barcodes[0]['type']
            }
        else:
            return {
                'success': False,
                'message': 'No readable barcode detected in this image. Please ensure the barcode is clearly visible, or enter the barcode number manually.'
            }
    except Exception as e:
        return {'success': False, 'message': str(e)}

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
            
        label = f"{b['type']}: {b['data']}"
        pos_y = max(25, b.get('rect', {}).get('y', 30) - 10)
        pos_x = b.get('rect', {}).get('x', 10)
        
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(annotated, (pos_x, pos_y - h - 5), (pos_x + w + 10, pos_y + 5), (0, 0, 0), -1)
        cv2.putText(annotated, label, (pos_x + 5, pos_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 128), 2)
        
    return annotated
