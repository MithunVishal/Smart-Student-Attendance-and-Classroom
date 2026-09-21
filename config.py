import os
import sys

# Base project directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Setup DLL directory for Windows Python 3.8+ so pyzbar can find msvcr120.dll
if hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(BASE_DIR)
    except Exception:
        pass
    
    site_pyzbar = os.path.join(sys.prefix, 'Lib', 'site-packages', 'pyzbar')
    if os.path.exists(site_pyzbar):
        try:
            os.add_dll_directory(site_pyzbar)
        except Exception:
            pass

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'iris-smart-attendance-system-key-2026')
    INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
    DATABASE_PATH = os.path.join(INSTANCE_DIR, 'attendance.db')
    
    STATIC_DIR = os.path.join(BASE_DIR, 'static')
    UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads')
    AVATARS_FOLDER = os.path.join(UPLOAD_FOLDER, 'avatars')
    BARCODE_FOLDER = os.path.join(STATIC_DIR, 'barcodes')
    REPORTS_FOLDER = os.path.join(STATIC_DIR, 'generated_reports')
    
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Classroom settings
    CLASSROOM_NAME = "Room 402 - Smart Computing Lab"
    CLASSROOM_CAPACITY = 60
    SCAN_COOLDOWN_SECONDS = 5  # Anti-flutter debounce between in/out scans for same student

# Ensure directories exist
for folder in [
    Config.INSTANCE_DIR,
    Config.STATIC_DIR,
    Config.UPLOAD_FOLDER,
    Config.AVATARS_FOLDER,
    Config.BARCODE_FOLDER,
    Config.REPORTS_FOLDER
]:
    os.makedirs(folder, exist_ok=True)
