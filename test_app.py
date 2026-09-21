import os
import io
import base64
import unittest
from datetime import datetime, timedelta
import cv2

from app import app
from database import init_db, get_db_connection, record_attendance_scan, get_dashboard_stats
from scanner import scan_barcodes_from_image, annotate_image_with_barcodes
from reports import export_to_csv, export_to_excel, export_to_pdf

class TestAttendanceSystem(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        init_db()

    def test_database_and_seeds(self):
        """Test that initial database seed creates sample students and barcodes."""
        conn = get_db_connection()
        students = conn.execute("SELECT * FROM students").fetchall()
        self.assertGreaterEqual(len(students), 8)
        
        # Verify barcode file exists for first student
        first_stu = students[0]
        barcode_file = os.path.join('static', 'barcodes', f"{first_stu['barcode_id']}.png")
        self.assertTrue(os.path.exists(barcode_file), f"Barcode file {barcode_file} should exist")
        conn.close()

    def test_opencv_pyzbar_scanner(self):
        """Test that OpenCV and Pyzbar decode a synthetic or generated Code128 barcode."""
        barcode_path = os.path.join('static', 'barcodes', 'STU2026001.png')
        img = cv2.imread(barcode_path)
        self.assertIsNotNone(img, "Failed to read barcode test image")
        
        results = scan_barcodes_from_image(img)
        self.assertGreater(len(results), 0, "Pyzbar should detect at least 1 barcode")
        self.assertEqual(results[0]['data'], 'STU2026001')
        self.assertIn('polygon', results[0])
        self.assertIn('rect', results[0])
        
        annotated = annotate_image_with_barcodes(img, results)
        self.assertEqual(annotated.shape, img.shape)

    def test_attendance_lifecycle(self):
        """Test the IN -> Cooldown -> OUT -> Duration lifecycle."""
        barcode_id = "STU2026007" # Priya Ramanathan (clean slate)
        
        # Ensure clean state today for STU2026007
        conn = get_db_connection()
        stu = conn.execute("SELECT id FROM students WHERE barcode_id = ?", (barcode_id,)).fetchone()
        today_str = datetime.now().strftime('%Y-%m-%d')
        conn.execute("DELETE FROM attendance WHERE student_id = ? AND date = ?", (stu['id'], today_str))
        conn.commit()
        conn.close()
        
        # 1. First Scan: Check-IN
        scan1_time = datetime(2026, 9, 21, 9, 0, 0)
        res1 = record_attendance_scan(barcode_id, scan_time=scan1_time)
        self.assertEqual(res1['status'], 'success')
        self.assertEqual(res1['action'], 'CHECK_IN')
        self.assertEqual(res1['attendance']['status'], 'Inside')
        self.assertEqual(res1['attendance']['in_time'], '09:00:00')
        self.assertIsNone(res1['attendance']['out_time'])
        
        # 2. Immediate scan within 5s: Cooldown
        scan_immediate = scan1_time + timedelta(seconds=2)
        res_cooldown = record_attendance_scan(barcode_id, scan_time=scan_immediate)
        self.assertEqual(res_cooldown['status'], 'cooldown')
        
        # 3. Second Scan after elapsed time: Check-OUT
        scan2_time = scan1_time + timedelta(hours=1, minutes=30, seconds=45)
        res2 = record_attendance_scan(barcode_id, scan_time=scan2_time)
        self.assertEqual(res2['status'], 'success')
        self.assertEqual(res2['action'], 'CHECK_OUT')
        self.assertEqual(res2['attendance']['status'], 'Exited')
        self.assertEqual(res2['attendance']['out_time'], '10:30:45')
        self.assertEqual(res2['attendance']['duration_seconds'], 5445)
        self.assertIn('1h 30m 45s', res2['attendance']['duration_formatted'])

    def test_flask_routes_and_api(self):
        """Test Flask web routes, authentication, and the camera scan frame API."""
        # 1. Login with demo admin credentials
        login_res = self.client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        self.assertEqual(login_res.status_code, 200)
        self.assertIn(b'Dashboard', login_res.data)
        
        # 2. Scanner page
        scanner_res = self.client.get('/scanner')
        self.assertEqual(scanner_res.status_code, 200)
        self.assertIn(b'Real-Time Barcode Scanner', scanner_res.data)
        
        # 3. Test /api/scan_frame with an encoded barcode frame
        with open('static/barcodes/STU2026001.png', 'rb') as f:
            b64_img = 'data:image/png;base64,' + base64.b64encode(f.read()).decode('utf-8')
            
        api_res = self.client.post('/api/scan_frame', json={'image': b64_img})
        self.assertEqual(api_res.status_code, 200)
        api_data = api_res.get_json()
        self.assertIn(api_data['status'], ['success', 'cooldown'])
        self.assertIn('barcode', api_data)
        
        # 4. Students directory
        students_res = self.client.get('/students')
        self.assertEqual(students_res.status_code, 200)
        self.assertIn(b'Aarav Sharma', students_res.data)
        
        # 5. ID Cards Gallery
        id_cards_res = self.client.get('/id-cards')
        self.assertEqual(id_cards_res.status_code, 200)
        self.assertIn(b'INSTITUTE OF TECHNOLOGY', id_cards_res.data)
        
        # 6. Attendance Table
        att_res = self.client.get('/attendance')
        self.assertEqual(att_res.status_code, 200)
        self.assertIn(b'Attendance Audit Records', att_res.data)
        
        # 7. Reports page
        rep_res = self.client.get('/reports')
        self.assertEqual(rep_res.status_code, 200)
        self.assertIn(b'Attendance Reports', rep_res.data)
        
        # 8. Export CSV, Excel, PDF endpoints
        csv_res = self.client.get('/reports/export/csv?report_type=daily')
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn(b'Register Number', csv_res.data)
        
        excel_res = self.client.get('/reports/export/excel?report_type=daily')
        self.assertEqual(excel_res.status_code, 200)
        self.assertGreater(len(excel_res.data), 1000)
        
        pdf_res = self.client.get('/reports/export/pdf?report_type=daily')
        self.assertEqual(pdf_res.status_code, 200)
        self.assertTrue(pdf_res.data.startswith(b'%PDF'))

if __name__ == '__main__':
    unittest.main()
