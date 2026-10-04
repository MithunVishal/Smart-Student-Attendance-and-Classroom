import os
import io
import base64
import unittest
from datetime import datetime, timedelta
import cv2

from app import app
from database import init_db, get_db_connection, record_attendance_scan, get_dashboard_stats
from scanner import scan_barcodes_from_image, annotate_image_with_barcodes, decode_barcode_from_file_bytes
from reports import export_to_csv, export_to_excel, export_to_pdf

class TestAttendanceSystem(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        init_db()

    def test_database_and_students(self):
        """Test that database contains real student records with AI & DS department."""
        conn = get_db_connection()
        students = conn.execute("SELECT * FROM students").fetchall()
        self.assertGreaterEqual(len(students), 5)
        
        # Verify first student has barcode_id and image
        first_stu = students[0]
        self.assertTrue(first_stu['barcode_id'].startswith('24AD'))
        self.assertEqual(first_stu['department'], 'Artificial Intelligence and Data Science')
        conn.close()

    def test_barcode_decoding_from_image(self):
        """Test dual-engine scanner extracts real barcode (Code39) from student ID card images."""
        test_card = os.path.join('static', 'barcodes', '24AD017_card.jpg')
        if os.path.exists(test_card):
            with open(test_card, 'rb') as f:
                card_bytes = f.read()
            res = decode_barcode_from_file_bytes(card_bytes)
            self.assertTrue(res.get('success'), f"Decode failed: {res.get('message')}")
            self.assertEqual(res.get('barcode_id'), '24AD017')

    def test_attendance_lifecycle(self):
        """Test the IN -> Cooldown -> OUT -> Duration lifecycle for real student 24AD017."""
        barcode_id = "24AD017"
        
        conn = get_db_connection()
        stu = conn.execute("SELECT id FROM students WHERE barcode_id = ?", (barcode_id,)).fetchone()
        self.assertIsNotNone(stu, f"Student {barcode_id} should exist")
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
        self.assertNotIn(b'Room 402', scanner_res.data) # Verify Room 402 was removed
        
        # 3. Test /api/decode_barcode_image endpoint
        test_card = os.path.join('static', 'barcodes', '24AD017_card.jpg')
        if os.path.exists(test_card):
            with open(test_card, 'rb') as f:
                card_content = f.read()
            upload_res = self.client.post(
                '/api/decode_barcode_image',
                data={'barcode_image': (io.BytesIO(card_content), 'card.jpeg')},
                content_type='multipart/form-data'
            )
            self.assertEqual(upload_res.status_code, 200)
            data = upload_res.get_json()
            self.assertTrue(data.get('success'), f"API decode error: {data}")
            self.assertEqual(data.get('barcode_id'), '24AD017')
        
        # 4. Students directory
        students_res = self.client.get('/students')
        self.assertEqual(students_res.status_code, 200)
        self.assertIn(b'Subash', students_res.data)
        self.assertIn(b'Artificial Intelligence and Data Science', students_res.data)
        
        # 5. Attendance Table
        att_res = self.client.get('/attendance')
        self.assertEqual(att_res.status_code, 200)
        self.assertIn(b'Attendance Audit Records', att_res.data)
        self.assertIn(b'Artificial Intelligence and Data Science', att_res.data)
        
        # 6. Reports page
        rep_res = self.client.get('/reports')
        self.assertEqual(rep_res.status_code, 200)
        self.assertIn(b'Attendance Reports', rep_res.data)
        self.assertIn(b'Artificial Intelligence and Data Science', rep_res.data)
        
        # 7. Export CSV, Excel, PDF endpoints
        csv_res = self.client.get('/reports/export/csv?report_type=daily')
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn(b'Register Number', csv_res.data)
        
        excel_res = self.client.get('/reports/export/excel?report_type=daily')
        self.assertEqual(excel_res.status_code, 200)
        self.assertGreater(len(excel_res.data), 1000)
        
        pdf_res = self.client.get('/reports/export/pdf?report_type=daily')
        self.assertEqual(pdf_res.status_code, 200)
        self.assertTrue(pdf_res.data.startswith(b'%PDF'))

    def test_energy_management(self):
        """Test the 3-zone energy management, manual toggle, calculations, and web routes."""
        # 1. Login
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        
        # 2. Get /energy page
        res = self.client.get('/energy')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Classroom Energy Management', res.data)
        self.assertIn(b'Zone 1', res.data)
        self.assertIn(b'Zone 2', res.data)
        self.assertIn(b'Zone 3', res.data)
        self.assertIn(b'795', res.data) # Reference Max
        
        # 3. Test /api/energy/status
        status_res = self.client.get('/api/energy/status')
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.get_json()
        self.assertTrue(status_data['success'])
        self.assertEqual(len(status_data['zones']), 3)
        self.assertEqual(status_data['metrics']['max_power_watts'], 795.0)
        
        # 4. Test turning all zones OFF
        toggle_off = self.client.post('/api/energy/toggle_all', json={'state': False})
        self.assertEqual(toggle_off.status_code, 200)
        data_off = toggle_off.get_json()
        self.assertEqual(data_off['metrics']['current_power_watts'], 0.0)
        self.assertEqual(data_off['metrics']['active_zones_count'], 0)
        
        # 5. Test turning Zone 1 ON (3 fans * 75W + 2 lights * 20W = 265W)
        toggle_z1 = self.client.post('/api/energy/toggle', json={'zone_number': 1, 'state': True})
        self.assertEqual(toggle_z1.status_code, 200)
        data_z1 = toggle_z1.get_json()
        self.assertEqual(data_z1['metrics']['current_power_watts'], 265.0)
        self.assertEqual(data_z1['metrics']['active_zones_count'], 1)
        z1 = [z for z in data_z1['zones'] if z['zone_number'] == 1][0]
        self.assertEqual(z1['working_fans'], 3)
        self.assertEqual(z1['working_lights'], 2)
        self.assertEqual(z1['current_power_watts'], 265.0)
        
        # 6. Test turning All zones ON (795W)
        toggle_all = self.client.post('/api/energy/toggle_all', json={'state': True})
        self.assertEqual(toggle_all.status_code, 200)
        data_all = toggle_all.get_json()
        self.assertEqual(data_all['metrics']['current_power_watts'], 795.0)
        self.assertEqual(data_all['metrics']['active_zones_count'], 3)

    def test_automatic_zone_and_temperature_control(self):
        """Test the automated zone activation (by student strength) and fan control (by temperature)."""
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})

        # 1. 0 Students -> All zones OFF
        res0 = self.client.post('/api/energy/settings', json={
            'control_mode': 'auto',
            'temperature': 28.0,
            'manual_student_override': 0
        })
        self.assertEqual(res0.status_code, 200)
        d0 = res0.get_json()['metrics']
        self.assertEqual(d0['active_zones_count'], 0)
        self.assertEqual(d0['fans_on'], 0)
        self.assertEqual(d0['lights_on'], 0)
        self.assertEqual(d0['current_power_watts'], 0.0)

        # 2. 6 Students (1–10) -> Zone 1 ON
        res1 = self.client.post('/api/energy/settings', json={
            'control_mode': 'auto',
            'temperature': 28.0,
            'manual_student_override': 6
        })
        d1 = res1.get_json()['metrics']
        self.assertEqual(d1['active_zones_count'], 1)
        self.assertEqual(d1['fans_on'], 3)
        self.assertEqual(d1['lights_on'], 2)
        self.assertEqual(d1['current_power_watts'], 265.0)

        # 3. 15 Students (11–20) at 28°C -> Zones 1 + 2 ON, Fans Full Speed
        res2 = self.client.post('/api/energy/settings', json={
            'control_mode': 'auto',
            'temperature': 28.0,
            'manual_student_override': 15
        })
        d2 = res2.get_json()['metrics']
        self.assertEqual(d2['active_zones_count'], 2)
        self.assertEqual(d2['fans_on'], 6)
        self.assertEqual(d2['lights_on'], 4)
        self.assertEqual(d2['current_power_watts'], 530.0)
        self.assertIn("2 Zones Active", d2['status_message'])
        self.assertIn("15 Students", d2['status_message'])
        self.assertIn("28°C", d2['status_message'])

        # 4. Temperature below 24°C (e.g. 22°C) -> Fans must turn OFF, Lights stay ON!
        res_cold = self.client.post('/api/energy/settings', json={
            'control_mode': 'auto',
            'temperature': 22.0,
            'manual_student_override': 15
        })
        d_cold = res_cold.get_json()['metrics']
        self.assertEqual(d_cold['active_zones_count'], 2)
        self.assertEqual(d_cold['fans_on'], 0) # Fans OFF below 24°C
        self.assertEqual(d_cold['lights_on'], 4) # Lights ON in active zones
        self.assertEqual(d_cold['current_power_watts'], 80.0) # 2 zones * 40W lights = 80W

        # 5. 25 Students (21+) at 30°C -> All 3 zones ON, 9 fans, 6 lights, 795W
        res3 = self.client.post('/api/energy/settings', json={
            'control_mode': 'auto',
            'temperature': 30.0,
            'manual_student_override': 25
        })
        d3 = res3.get_json()['metrics']
        self.assertEqual(d3['active_zones_count'], 3)
        self.assertEqual(d3['fans_on'], 9)
        self.assertEqual(d3['lights_on'], 6)
        self.assertEqual(d3['current_power_watts'], 795.0)

        # 6. Mode Switch: Manual Mode
        res_man = self.client.post('/api/energy/settings', json={'control_mode': 'manual'})
        d_man = res_man.get_json()['metrics']
        self.assertEqual(d_man['control_mode'], 'manual')

if __name__ == '__main__':
    unittest.main()

