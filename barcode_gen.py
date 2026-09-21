import os
import barcode
from barcode.writer import ImageWriter
from config import Config

def generate_barcode_image(barcode_id: str) -> str:
    """
    Generates a Code128 barcode PNG image for the given barcode_id.
    Saves it in Config.BARCODE_FOLDER and returns the relative path for web serving.
    """
    clean_id = "".join(c for c in barcode_id if c.isalnum() or c in ('-', '_')).strip()
    if not clean_id:
        clean_id = "BARCODE"
        
    filename = f"{clean_id}"
    full_path_no_ext = os.path.join(Config.BARCODE_FOLDER, filename)
    
    # Generate Code128 barcode
    code128 = barcode.get_barcode_class('code128')
    writer = ImageWriter()
    writer.set_options({
        'module_width': 0.35,     # Width of single bar
        'module_height': 15.0,    # Height of bar in mm
        'quiet_zone': 4.0,        # Margin around barcode
        'font_size': 10,          # Size of text under barcode
        'text_distance': 4.0,     # Space between barcode and text
        'write_text': True,       # Render text under barcode
    })
    
    barcode_instance = code128(clean_id, writer=writer)
    saved_filename = barcode_instance.save(full_path_no_ext)
    
    # Relative path from static/
    rel_path = f"barcodes/{os.path.basename(saved_filename)}"
    return rel_path

def get_or_create_barcode_image(barcode_id: str) -> str:
    """
    Returns existing barcode image path or creates one if it doesn't exist.
    """
    expected_path = os.path.join(Config.BARCODE_FOLDER, f"{barcode_id}.png")
    if os.path.exists(expected_path):
        return f"barcodes/{barcode_id}.png"
    return generate_barcode_image(barcode_id)
