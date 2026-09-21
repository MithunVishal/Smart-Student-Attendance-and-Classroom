import os
import sqlite3
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont
from config import Config
from barcode_gen import get_or_create_barcode_image

def get_db_connection():
    """Returns a connection to the SQLite database with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def format_duration(seconds: int) -> str:
    """Formats a duration in seconds into human-readable string like '1h 24m' or '45m 10s'."""
    if seconds is None or seconds < 0:
        return "0m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    rem_seconds = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{rem_seconds}s")
    
    return " ".join(parts)

def init_db():
    """Initializes the database schema and seeds initial data if empty."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. Students table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT NOT NULL,
        register_number TEXT UNIQUE NOT NULL,
        department TEXT NOT NULL,
        year TEXT NOT NULL,
        section TEXT NOT NULL,
        photo_path TEXT,
        barcode_id TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 3. Attendance table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        in_time TEXT NOT NULL,
        out_time TEXT,
        duration_seconds INTEGER DEFAULT 0,
        duration_formatted TEXT DEFAULT '0s',
        status TEXT NOT NULL DEFAULT 'Inside',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    
    # Check if admin user exists
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            ('admin', generate_password_hash('admin123'), 'System Administrator', 'admin')
        )
        conn.commit()
        
    conn.close()
    seed_initial_data()

def create_sample_avatar(name: str, bg_color: tuple, text_color: tuple = (255, 255, 255)) -> str:
    """Generates an initial avatar image if custom photo is not provided."""
    filename = f"avatar_{name.lower().replace(' ', '_')}.png"
    filepath = os.path.join(Config.AVATARS_FOLDER, filename)
    if os.path.exists(filepath):
        return f"uploads/avatars/{filename}"
    
    size = (300, 300)
    img = Image.new('RGB', size, color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Get initials
    initials = "".join([part[0].upper() for part in name.split()[:2]])
    if not initials:
        initials = "ST"
        
    try:
        font = ImageFont.truetype("arial.ttf", 110)
    except Exception:
        font = ImageFont.load_default()
        
    # Center text
    bbox = draw.textbbox((0, 0), initials, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size[0] - w) / 2
    y = (size[1] - h) / 2 - 10
    draw.text((x, y), initials, fill=text_color, font=font)
    
    img.save(filepath)
    return f"uploads/avatars/{filename}"

def seed_initial_data():
    """Seeds realistic sample students, barcodes, and attendance logs for demonstration."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM students")
    count = cursor.fetchone()['count']
    
    if count == 0:
        sample_students = [
            ("Aarav Sharma", "2026CS101", "Computer Science", "3rd Year", "A", "STU2026001", (26, 86, 219)),
            ("Ananya Patel", "2026CS102", "Computer Science", "3rd Year", "A", "STU2026002", (15, 118, 110)),
            ("Rohan Verma", "2026IT201", "Information Technology", "2nd Year", "B", "STU2026003", (180, 83, 9)),
            ("Sneha Nair", "2026EC301", "Electronics & Comm.", "4th Year", "A", "STU2026004", (109, 40, 217)),
            ("Vikram Aditya", "2026CS103", "Computer Science", "3rd Year", "B", "STU2026005", (190, 24, 93)),
            ("Kavya Sundaram", "2026ME401", "Mechanical Eng.", "1st Year", "A", "STU2026006", (3, 105, 161)),
            ("Priya Ramanathan", "2026IT202", "Information Technology", "2nd Year", "A", "STU2026007", (67, 56, 202)),
            ("Karthik Raja", "2026CV501", "Civil Engineering", "4th Year", "B", "STU2026008", (55, 65, 81))
        ]
        
        today_str = date.today().strftime('%Y-%m-%d')
        now = datetime.now()
        
        for name, reg_no, dept, year, sec, barcode_id, color in sample_students:
            # 1. Create avatar
            photo_path = create_sample_avatar(name, color)
            
            # 2. Generate Barcode PNG
            get_or_create_barcode_image(barcode_id)
            
            # 3. Insert student
            cursor.execute("""
            INSERT INTO students (student_name, register_number, department, year, section, photo_path, barcode_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, reg_no, dept, year, sec, photo_path, barcode_id))
            student_id = cursor.lastrowid
            
            # 4. Seed realistic today attendance for first 4 students
            if barcode_id == "STU2026001":
                # Currently inside
                in_time = (now - timedelta(minutes=45)).strftime('%H:%M:%S')
                cursor.execute("""
                INSERT INTO attendance (student_id, date, in_time, out_time, duration_seconds, duration_formatted, status)
                VALUES (?, ?, ?, NULL, 0, '0s', 'Inside')
                """, (student_id, today_str, in_time))
            elif barcode_id == "STU2026002":
                # Completed session (exited)
                in_time = (now - timedelta(hours=2, minutes=10)).strftime('%H:%M:%S')
                out_time = (now - timedelta(minutes=35)).strftime('%H:%M:%S')
                dur_secs = 95 * 60
                cursor.execute("""
                INSERT INTO attendance (student_id, date, in_time, out_time, duration_seconds, duration_formatted, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Exited')
                """, (student_id, today_str, in_time, out_time, dur_secs, format_duration(dur_secs)))
            elif barcode_id == "STU2026003":
                # Currently inside
                in_time = (now - timedelta(minutes=20)).strftime('%H:%M:%S')
                cursor.execute("""
                INSERT INTO attendance (student_id, date, in_time, out_time, duration_seconds, duration_formatted, status)
                VALUES (?, ?, ?, NULL, 0, '0s', 'Inside')
                """, (student_id, today_str, in_time))
            elif barcode_id == "STU2026004":
                # Completed session (exited)
                in_time = (now - timedelta(hours=1, minutes=40)).strftime('%H:%M:%S')
                out_time = (now - timedelta(minutes=15)).strftime('%H:%M:%S')
                dur_secs = 85 * 60
                cursor.execute("""
                INSERT INTO attendance (student_id, date, in_time, out_time, duration_seconds, duration_formatted, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Exited')
                """, (student_id, today_str, in_time, out_time, dur_secs, format_duration(dur_secs)))
                
        conn.commit()
        
    conn.close()

def get_student_by_barcode(barcode_id: str):
    """Fetches a student by their unique barcode_id."""
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE barcode_id = ?", (barcode_id,)).fetchone()
    conn.close()
    return dict(student) if student else None

def record_attendance_scan(barcode_id: str, scan_time: datetime = None):
    """
    Core attendance engine:
    - Decodes barcode and matches student.
    - If student is currently Inside (active session today):
      - Checks cooldown.
      - If cooldown passed: marks OUT time, calculates duration, updates status to 'Exited'.
    - If student is NOT currently Inside:
      - Marks IN time, sets status to 'Inside'.
    """
    if scan_time is None:
        scan_time = datetime.now()
        
    today_str = scan_time.strftime('%Y-%m-%d')
    time_str = scan_time.strftime('%H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Match student
    cursor.execute("SELECT * FROM students WHERE barcode_id = ?", (barcode_id,))
    student_row = cursor.fetchone()
    
    if not student_row:
        conn.close()
        return {
            'status': 'not_found',
            'barcode_id': barcode_id,
            'message': f"Barcode '{barcode_id}' is detected, but not registered in the student database."
        }
        
    student = dict(student_row)
    student_id = student['id']
    
    # 2. Check for active 'Inside' record today
    cursor.execute("""
    SELECT * FROM attendance
    WHERE student_id = ? AND date = ? AND status = 'Inside'
    ORDER BY id DESC LIMIT 1
    """, (student_id, today_str))
    active_record = cursor.fetchone()
    
    if active_record:
        # Existing session inside - Process CHECK-OUT
        record_id = active_record['id']
        in_time_str = active_record['in_time']
        
        # Calculate duration
        try:
            in_datetime = datetime.strptime(f"{today_str} {in_time_str}", '%Y-%m-%d %H:%M:%S')
            duration_secs = int((scan_time - in_datetime).total_seconds())
        except Exception:
            duration_secs = 0
            
        # Cooldown guard: prevent double-scan within threshold seconds
        if duration_secs < Config.SCAN_COOLDOWN_SECONDS:
            remaining = Config.SCAN_COOLDOWN_SECONDS - duration_secs
            conn.close()
            return {
                'status': 'cooldown',
                'action': 'COOLDOWN',
                'barcode_id': barcode_id,
                'student': student,
                'message': f"Already checked IN! Please wait {remaining}s before checking OUT.",
                'remaining_seconds': remaining
            }
            
        duration_formatted = format_duration(duration_secs)
        
        cursor.execute("""
        UPDATE attendance
        SET out_time = ?, duration_seconds = ?, duration_formatted = ?, status = 'Exited'
        WHERE id = ?
        """, (time_str, duration_secs, duration_formatted, record_id))
        conn.commit()
        
        # Fetch updated record
        cursor.execute("SELECT * FROM attendance WHERE id = ?", (record_id,))
        updated_record = dict(cursor.fetchone())
        conn.close()
        
        return {
            'status': 'success',
            'action': 'CHECK_OUT',
            'barcode_id': barcode_id,
            'student': student,
            'attendance': updated_record,
            'message': f"Check-OUT Successful! Goodbye, {student['student_name']}. Total Duration: {duration_formatted}."
        }
        
    else:
        # No active inside session - Process CHECK-IN
        cursor.execute("""
        INSERT INTO attendance (student_id, date, in_time, out_time, duration_seconds, duration_formatted, status)
        VALUES (?, ?, ?, NULL, 0, '0s', 'Inside')
        """, (student_id, today_str, time_str))
        conn.commit()
        record_id = cursor.lastrowid
        
        cursor.execute("SELECT * FROM attendance WHERE id = ?", (record_id,))
        new_record = dict(cursor.fetchone())
        conn.close()
        
        return {
            'status': 'success',
            'action': 'CHECK_IN',
            'barcode_id': barcode_id,
            'student': student,
            'attendance': new_record,
            'message': f"Check-IN Successful! Welcome, {student['student_name']}. Recorded IN Time: {time_str}."
        }

def get_dashboard_stats(target_date: str = None):
    """Aggregates all 6 core dashboard metrics, charts data, and live recent activity."""
    if target_date is None:
        target_date = date.today().strftime('%Y-%m-%d')
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Total Students
    cursor.execute("SELECT COUNT(*) as total FROM students")
    total_students = cursor.fetchone()['total']
    
    # 2. Present Students Today (Distinct students with attendance record today)
    cursor.execute("SELECT COUNT(DISTINCT student_id) as present FROM attendance WHERE date = ?", (target_date,))
    present_students = cursor.fetchone()['present']
    
    # 3. Absent Students Today
    absent_students = max(0, total_students - present_students)
    
    # 4. Students Currently Inside
    cursor.execute("SELECT COUNT(*) as inside FROM attendance WHERE date = ? AND status = 'Inside'", (target_date,))
    students_inside = cursor.fetchone()['inside']
    
    # 5. Students Exited Today (Students who have checked out and are not currently inside)
    cursor.execute("""
    SELECT COUNT(DISTINCT a.student_id) as exited
    FROM attendance a
    WHERE a.date = ? AND a.status = 'Exited'
      AND a.student_id NOT IN (
          SELECT student_id FROM attendance WHERE date = ? AND status = 'Inside'
      )
    """, (target_date, target_date))
    students_exited = cursor.fetchone()['exited']
    
    # 6. Daily Attendance Percentage
    attendance_pct = round((present_students / total_students * 100), 1) if total_students > 0 else 0.0
    
    # Classroom Occupancy Percentage
    capacity = Config.CLASSROOM_CAPACITY
    occupancy_pct = round((students_inside / capacity * 100), 1) if capacity > 0 else 0.0
    
    # Department Breakdown
    cursor.execute("""
    SELECT s.department, COUNT(DISTINCT s.id) as count
    FROM students s
    JOIN attendance a ON s.id = a.student_id
    WHERE a.date = ?
    GROUP BY s.department
    """, (target_date,))
    dept_rows = cursor.fetchall()
    department_stats = {row['department']: row['count'] for row in dept_rows}
    
    # Hourly Traffic (Distribution of IN checkins across 24 hours)
    cursor.execute("""
    SELECT substr(in_time, 1, 2) as hour, COUNT(*) as count
    FROM attendance
    WHERE date = ?
    GROUP BY hour
    ORDER BY hour
    """, (target_date,))
    hourly_rows = cursor.fetchall()
    hourly_traffic = {f"{int(r['hour']):02d}:00": r['count'] for r in hourly_rows}
    
    # Recent Scans Activity Feed (Last 10)
    cursor.execute("""
    SELECT a.*, s.student_name, s.register_number, s.department, s.photo_path, s.barcode_id
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE a.date = ?
    ORDER BY a.id DESC
    LIMIT 10
    """, (target_date,))
    recent_scans = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        'target_date': target_date,
        'total_students': total_students,
        'present_students': present_students,
        'absent_students': absent_students,
        'students_inside': students_inside,
        'students_exited': students_exited,
        'attendance_percentage': attendance_pct,
        'classroom_name': Config.CLASSROOM_NAME,
        'classroom_capacity': capacity,
        'occupancy_percentage': occupancy_pct,
        'department_stats': department_stats,
        'hourly_traffic': hourly_traffic,
        'recent_scans': recent_scans
    }

def get_attendance_records(target_date: str = None, department: str = None, status: str = None, search: str = None):
    """Queries attendance records with flexible filters and search."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT a.*, s.student_name, s.register_number, s.department, s.year, s.section, s.photo_path, s.barcode_id
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE 1=1
    """
    params = []
    
    if target_date:
        query += " AND a.date = ?"
        params.append(target_date)
        
    if department and department != 'All':
        query += " AND s.department = ?"
        params.append(department)
        
    if status and status != 'All':
        query += " AND a.status = ?"
        params.append(status)
        
    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (s.student_name LIKE ? OR s.register_number LIKE ? OR s.barcode_id LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern])
        
    query += " ORDER BY a.id DESC"
    
    cursor.execute(query, params)
    records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return records

def get_all_students(search: str = None, department: str = None):
    """Retrieves all students with optional search and department filtering."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM students WHERE 1=1"
    params = []
    
    if department and department != 'All':
        query += " AND department = ?"
        params.append(department)
        
    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (student_name LIKE ? OR register_number LIKE ? OR barcode_id LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern])
        
    query += " ORDER BY register_number ASC"
    cursor.execute(query, params)
    students = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return students
