import os
import sqlite3
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont
from config import Config

def get_db_connection():
    """Returns a connection to the SQLite database with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def format_duration(seconds: int) -> str:
    """Formats a duration in seconds into human-readable string like '1h 24m' or '45m 10s'."""
    if seconds is None or seconds < 0:
        return "0s"
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
    """Initializes the database schema and ensures all required columns exist."""
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
        barcode_image_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Check if barcode_image_path column exists in older database
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN barcode_image_path TEXT")
        conn.commit()
    except Exception:
        pass
    
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
        
    # Link barcode images for existing students if not set
    cursor.execute("SELECT id, barcode_id, student_name FROM students WHERE barcode_image_path IS NULL OR barcode_image_path = ''")
    for s in cursor.fetchall():
        bid = s['barcode_id']
        name = s['student_name'].lower()
        possible_imgs = [f"barcodes/{bid}.png", f"barcodes/{bid}.jpg", f"barcodes/{bid}.jpeg"]
        for f in os.listdir(Config.BARCODE_FOLDER):
            if name in f.lower() or bid.lower() in f.lower():
                possible_imgs.insert(0, f"barcodes/{f}")
        for img in possible_imgs:
            if os.path.exists(os.path.join(Config.STATIC_DIR, img)):
                cursor.execute("UPDATE students SET barcode_image_path = ? WHERE id = ?", (img, s['id']))
                break
    conn.commit()
    
    # Initialize energy management zones & historical tables
    init_energy_tables(cursor, conn)
    
    conn.close()

def create_sample_avatar(name: str, bg_color: tuple = (30, 64, 175), text_color: tuple = (255, 255, 255)) -> str:
    """Generates an initial avatar image if custom photo is not provided."""
    filename = f"avatar_{name.lower().replace(' ', '_')}.png"
    filepath = os.path.join(Config.AVATARS_FOLDER, filename)
    if os.path.exists(filepath):
        return f"uploads/avatars/{filename}"
    
    size = (300, 300)
    img = Image.new('RGB', size, color=bg_color)
    draw = ImageDraw.Draw(img)
    
    initials = "".join([part[0].upper() for part in name.split()[:2]])
    if not initials:
        initials = "ST"
        
    try:
        font = ImageFont.truetype("arial.ttf", 110)
    except Exception:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), initials, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size[0] - w) / 2
    y = (size[1] - h) / 2 - 10
    draw.text((x, y), initials, fill=text_color, font=font)
    
    img.save(filepath)
    return f"uploads/avatars/{filename}"

def get_student_by_barcode(barcode_id: str):
    """Fetches a student by their unique barcode_id (case-insensitive & trimmed)."""
    conn = get_db_connection()
    clean_id = barcode_id.strip()
    student = conn.execute(
        "SELECT * FROM students WHERE UPPER(barcode_id) = UPPER(?)", (clean_id,)
    ).fetchone()
    conn.close()
    return dict(student) if student else None

def record_attendance_scan(barcode_id: str, scan_time: datetime = None):
    """
    Core attendance scan engine:
    - Scans and matches student by exact barcode number.
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
    clean_barcode = barcode_id.strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Match student by barcode
    cursor.execute("SELECT * FROM students WHERE UPPER(barcode_id) = UPPER(?)", (clean_barcode,))
    student_row = cursor.fetchone()
    
    if not student_row:
        conn.close()
        return {
            'status': 'not_found',
            'barcode_id': clean_barcode,
            'message': f"Barcode '{clean_barcode}' was scanned, but is not registered in the student database."
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
                'barcode_id': clean_barcode,
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
        
        cursor.execute("SELECT * FROM attendance WHERE id = ?", (record_id,))
        updated_record = dict(cursor.fetchone())
        conn.close()
        
        try:
            sync_automatic_energy_state()
        except Exception:
            pass
            
        return {
            'status': 'success',
            'action': 'CHECK_OUT',
            'barcode_id': clean_barcode,
            'student': student,
            'attendance': updated_record,
            'message': f"Check-OUT Successful! {student['student_name']} (Barcode: {clean_barcode}) checked OUT at {time_str}. Duration: {duration_formatted}."
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
        
        try:
            sync_automatic_energy_state()
        except Exception:
            pass
            
        return {
            'status': 'success',
            'action': 'CHECK_IN',
            'barcode_id': clean_barcode,
            'student': student,
            'attendance': new_record,
            'message': f"Check-IN Successful! {student['student_name']} (Barcode: {clean_barcode}) checked IN at {time_str}."
        }

def get_dashboard_stats(target_date: str = None):
    """Aggregates attendance metrics, charts data, and live recent activity."""
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
    
    # 5. Students Exited Today
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
    
    # Hourly Traffic
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

# ==========================================
# ENERGY MANAGEMENT & CLASSROOM ZONES
# ==========================================

FAN_DEFAULT_WATTS = 75.0
LIGHT_DEFAULT_WATTS = 20.0
TARIFF_PER_KWH = 8.00  # Standard institutional rate in INR (or currency units)

def init_energy_tables(cursor, conn):
    """Initializes the energy zones, settings, and energy history tables with default configurations."""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS energy_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone_number INTEGER UNIQUE NOT NULL,
        zone_name TEXT NOT NULL,
        is_active INTEGER DEFAULT 0,
        fans_count INTEGER DEFAULT 3,
        lights_count INTEGER DEFAULT 2,
        fan_power_watts REAL DEFAULT 75.0,
        light_power_watts REAL DEFAULT 20.0,
        last_turned_on TEXT,
        total_operating_seconds_today INTEGER DEFAULT 0,
        total_kwh_today REAL DEFAULT 0.0,
        last_date TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS energy_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        control_mode TEXT DEFAULT 'auto',
        temperature REAL DEFAULT 28.0,
        manual_student_override INTEGER DEFAULT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS energy_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        total_kwh REAL NOT NULL DEFAULT 0.0,
        baseline_kwh REAL NOT NULL DEFAULT 0.0,
        saved_kwh REAL NOT NULL DEFAULT 0.0,
        saving_percentage REAL NOT NULL DEFAULT 0.0,
        cost_consumed REAL NOT NULL DEFAULT 0.0,
        cost_saved REAL NOT NULL DEFAULT 0.0,
        operating_hours REAL NOT NULL DEFAULT 0.0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    today_str = date.today().strftime('%Y-%m-%d')
    
    # Seed default energy settings (Auto mode, 28°C, Live attendance)
    cursor.execute("SELECT COUNT(*) as count FROM energy_settings")
    s_row = cursor.fetchone()
    if s_row and s_row['count'] == 0:
        cursor.execute("""
        INSERT INTO energy_settings (control_mode, temperature, manual_student_override)
        VALUES ('auto', 28.0, NULL)
        """)
        conn.commit()
    
    # Seed 3 default classroom zones if not yet existing
    cursor.execute("SELECT COUNT(*) as count FROM energy_zones")
    row = cursor.fetchone()
    if row and row['count'] == 0:
        default_zones = [
            (1, "Zone 1 (Front Row / Lectern)", 1, 3, 2, 75.0, 20.0, 5400),
            (2, "Zone 2 (Middle Classroom)", 1, 3, 2, 75.0, 20.0, 4800),
            (3, "Zone 3 (Rear Classroom)", 0, 3, 2, 75.0, 20.0, 0)
        ]
        for zn, name, active, fans, lights, fp, lp, op_sec in default_zones:
            zone_watts = (fans * fp) + (lights * lp) # 265W
            kwh = round((zone_watts * (op_sec / 3600.0)) / 1000.0, 4)
            last_on = datetime.now().isoformat() if active else None
            cursor.execute("""
            INSERT INTO energy_zones (
                zone_number, zone_name, is_active, fans_count, lights_count,
                fan_power_watts, light_power_watts, last_turned_on,
                total_operating_seconds_today, total_kwh_today, last_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (zn, name, active, fans, lights, fp, lp, last_on, op_sec, kwh, today_str))
        conn.commit()

    # Seed realistic 7-day history if empty
    cursor.execute("SELECT COUNT(*) as count FROM energy_history")
    h_row = cursor.fetchone()
    if h_row and h_row['count'] == 0:
        sample_days = [
            (6, 6.5, 0.67, "Zone 3 kept OFF during morning classes. 33.3% energy saved vs full baseline."),
            (5, 7.0, 0.60, "Zone 1 & 2 operated continuously; Zone 3 activated only during afternoon lab."),
            (4, 6.0, 0.55, "Smart zone efficiency active; reduced load for small batches."),
            (3, 7.5, 0.70, "Full day lectures; rear zone managed dynamically according to student count."),
            (2, 5.5, 0.50, "Half-day seminar; only Zone 1 utilized for front seating."),
            (1, 6.0, 0.65, "Regular classroom schedule; energy savings recorded.")
        ]
        for days_ago, op_hours, ratio, note in sample_days:
            past_date = (date.today() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
            base_kwh = round(0.795 * op_hours, 2)
            act_kwh = round(base_kwh * ratio, 2)
            sv_kwh = round(base_kwh - act_kwh, 2)
            sv_pct = round((sv_kwh / base_kwh) * 100.0, 1) if base_kwh > 0 else 0.0
            cost_c = round(act_kwh * TARIFF_PER_KWH, 2)
            cost_s = round(sv_kwh * TARIFF_PER_KWH, 2)
            cursor.execute("""
            INSERT OR IGNORE INTO energy_history
            (date, total_kwh, baseline_kwh, saved_kwh, saving_percentage, cost_consumed, cost_saved, operating_hours, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (past_date, act_kwh, base_kwh, sv_kwh, sv_pct, cost_c, cost_s, op_hours, note))
        conn.commit()

def get_energy_settings():
    """Retrieves current energy control settings (Auto/Manual mode, temperature, student override)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM energy_settings ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
        INSERT INTO energy_settings (control_mode, temperature, manual_student_override)
        VALUES ('auto', 28.0, NULL)
        """)
        conn.commit()
        cursor.execute("SELECT * FROM energy_settings ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
    settings = dict(row)
    conn.close()
    return settings

def update_energy_settings(control_mode=None, temperature=None, manual_student_override="NO_CHANGE"):
    """Updates energy control settings and applies automated adjustments if in Auto mode."""
    conn = get_db_connection()
    cursor = conn.cursor()
    current = get_energy_settings()
    
    new_mode = control_mode if control_mode is not None else current['control_mode']
    new_temp = float(temperature) if temperature is not None else float(current['temperature'])
    new_override = current['manual_student_override'] if manual_student_override == "NO_CHANGE" else manual_student_override
    
    cursor.execute("""
    UPDATE energy_settings
    SET control_mode = ?, temperature = ?, manual_student_override = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (new_mode, new_temp, new_override, current['id']))
    conn.commit()
    conn.close()
    
    if new_mode == 'auto':
        sync_automatic_energy_state()
        
    return get_energy_dashboard_metrics()

def get_current_student_count(target_date: str = None):
    """Returns currently present students (Inside), respecting manual demonstration override if set."""
    settings = get_energy_settings()
    if settings.get('manual_student_override') is not None:
        return int(settings['manual_student_override'])
        
    if not target_date:
        target_date = date.today().strftime('%Y-%m-%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as inside FROM attendance WHERE date = ? AND status = 'Inside'", (target_date,))
    row = cursor.fetchone()
    count = row['inside'] if row else 0
    conn.close()
    return count

def sync_automatic_energy_state():
    """
    Automates zone activation according to student strength:
      * 0 students -> All zones OFF
      * 1–10 students -> Zone 1 ON
      * 11–20 students -> Zones 1 + 2 ON
      * 21+ students -> Zones 1 + 2 + 3 ON
    """
    settings = get_energy_settings()
    if settings.get('control_mode') != 'auto':
        return
        
    student_count = get_current_student_count()
    
    if student_count <= 0:
        target_zones = {1: False, 2: False, 3: False}
    elif student_count <= 10:
        target_zones = {1: True, 2: False, 3: False}
    elif student_count <= 20:
        target_zones = {1: True, 2: True, 3: False}
    else:
        target_zones = {1: True, 2: True, 3: True}
        
    for zn, should_be_active in target_zones.items():
        toggle_energy_zone(zn, target_state=should_be_active, switch_to_manual=False)

def check_and_rollover_energy_day(conn):
    """Checks if the date has changed since the last recorded energy operation and archives daily metrics."""
    today_str = date.today().strftime('%Y-%m-%d')
    cursor = conn.cursor()
    cursor.execute("SELECT last_date FROM energy_zones WHERE last_date IS NOT NULL LIMIT 1")
    row = cursor.fetchone()
    if row and row['last_date'] and row['last_date'] != today_str:
        old_date = row['last_date']
        # Archive yesterday's data into energy_history
        cursor.execute("SELECT SUM(total_kwh_today) as total_kwh, MAX(total_operating_seconds_today) as max_sec FROM energy_zones")
        summary = cursor.fetchone()
        if summary and summary['total_kwh'] is not None:
            act_kwh = round(summary['total_kwh'], 2)
            max_sec = summary['max_sec'] or 0
            op_hours = round(max_sec / 3600.0, 2)
            base_kwh = round(0.795 * max(op_hours, 1.0), 2)
            if base_kwh < act_kwh:
                base_kwh = act_kwh
            sv_kwh = round(base_kwh - act_kwh, 2)
            sv_pct = round((sv_kwh / base_kwh) * 100.0, 1) if base_kwh > 0 else 0.0
            cost_c = round(act_kwh * TARIFF_PER_KWH, 2)
            cost_s = round(sv_kwh * TARIFF_PER_KWH, 2)
            
            cursor.execute("""
            INSERT OR REPLACE INTO energy_history
            (date, total_kwh, baseline_kwh, saved_kwh, saving_percentage, cost_consumed, cost_saved, operating_hours, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (old_date, act_kwh, base_kwh, sv_kwh, sv_pct, cost_c, cost_s, op_hours, "Daily classroom energy log"))
        
        # Reset zones for the new day
        cursor.execute("""
        UPDATE energy_zones
        SET total_operating_seconds_today = 0,
            total_kwh_today = 0.0,
            last_date = ?,
            last_turned_on = CASE WHEN is_active = 1 THEN ? ELSE NULL END
        """, (today_str, datetime.now().isoformat()))
        conn.commit()

def get_energy_zones_status():
    """
    Retrieves real-time status, live power, operating time, and kWh for each of the 3 zones.
    Incorporates temperature-based fan control and occupancy-based light control:
      * Below 24°C -> Fans OFF
      * 24–27°C -> Fans ON at normal/low speed
      * Above 27°C -> Fans ON at full speed
      * Lights ON only in active zones
    """
    conn = get_db_connection()
    check_and_rollover_energy_day(conn)
    
    settings = get_energy_settings()
    temperature = float(settings.get('temperature', 28.0))
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM energy_zones ORDER BY zone_number ASC")
    rows = cursor.fetchall()
    now = datetime.now()
    
    zones = []
    for r in rows:
        z_dict = dict(r)
        is_active = bool(z_dict['is_active'])
        fp = float(z_dict['fan_power_watts'])   # 75W
        lp = float(z_dict['light_power_watts']) # 20W
        fans = int(z_dict['fans_count'])        # 3
        lights = int(z_dict['lights_count'])    # 2
        
        # 1. Lights control: Lights ON only in active zones
        working_lights = lights if is_active else 0
        light_watts = (lights * lp) if is_active else 0.0
        
        # 2. Temperature fan control:
        # Below 24°C -> Fans OFF
        # 24–27°C -> Fans ON at low/normal operation
        # Above 27°C -> Fans ON at full operation
        if not is_active or temperature < 24.0:
            working_fans = 0
            fan_watts = 0.0
            fan_status = "OFF (<24°C)" if is_active else "OFF"
            fan_speed = "off"
        elif 24.0 <= temperature <= 27.0:
            working_fans = fans
            fan_watts = fans * fp
            fan_status = "Normal / Low (24–27°C)"
            fan_speed = "normal"
        else: # > 27.0°C
            working_fans = fans
            fan_watts = fans * fp
            fan_status = "Full Power (>27°C)"
            fan_speed = "full"
            
        curr_watts = fan_watts + light_watts
        rated_zone_watts = (fans * fp) + (lights * lp) # 265 W rated max
        
        live_sec = int(z_dict['total_operating_seconds_today'] or 0)
        live_kwh = float(z_dict['total_kwh_today'] or 0.0)
        
        if is_active and z_dict['last_turned_on']:
            try:
                last_on_dt = datetime.fromisoformat(z_dict['last_turned_on'])
                elapsed = max(0, int((now - last_on_dt).total_seconds()))
                live_sec += elapsed
                live_kwh += (curr_watts * (elapsed / 3600.0)) / 1000.0
            except Exception:
                pass
                
        z_dict['is_active'] = is_active
        z_dict['working_fans'] = working_fans
        z_dict['working_lights'] = working_lights
        z_dict['fan_status'] = fan_status
        z_dict['fan_speed'] = fan_speed
        z_dict['fan_watts'] = round(fan_watts, 1)
        z_dict['light_watts'] = round(light_watts, 1)
        z_dict['rated_zone_watts'] = round(rated_zone_watts, 1)
        z_dict['current_power_watts'] = round(curr_watts, 1)
        z_dict['operating_seconds'] = live_sec
        z_dict['operating_time_formatted'] = format_duration(live_sec)
        z_dict['energy_kwh'] = round(live_kwh, 4)
        
        zones.append(z_dict)
        
    conn.close()
    return zones

def toggle_energy_zone(zone_number: int, target_state: bool = None, switch_to_manual: bool = True):
    """Toggles an energy zone ON/OFF and accumulates operating seconds and kWh."""
    conn = get_db_connection()
    check_and_rollover_energy_day(conn)
    
    if switch_to_manual:
        # If teacher manually clicks a zone button, switch mode to manual
        conn.execute("UPDATE energy_settings SET control_mode = 'manual', updated_at = CURRENT_TIMESTAMP")
        conn.commit()
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM energy_zones WHERE zone_number = ?", (zone_number,))
    zone = cursor.fetchone()
    if not zone:
        conn.close()
        return None
        
    now = datetime.now()
    current_active = bool(zone['is_active'])
    new_active = (not current_active) if target_state is None else target_state
    
    fp = float(zone['fan_power_watts'])
    lp = float(zone['light_power_watts'])
    fans = int(zone['fans_count'])
    lights = int(zone['lights_count'])
    rated_zone_watts = (fans * fp) + (lights * lp)
    
    tot_sec = int(zone['total_operating_seconds_today'] or 0)
    tot_kwh = float(zone['total_kwh_today'] or 0.0)
    
    if current_active:
        if zone['last_turned_on']:
            try:
                last_on_dt = datetime.fromisoformat(zone['last_turned_on'])
                elapsed = max(0, int((now - last_on_dt).total_seconds()))
                tot_sec += elapsed
                tot_kwh += (rated_zone_watts * (elapsed / 3600.0)) / 1000.0
            except Exception:
                pass
                
    new_last_on = now.isoformat() if new_active else None
    
    cursor.execute("""
    UPDATE energy_zones
    SET is_active = ?,
        last_turned_on = ?,
        total_operating_seconds_today = ?,
        total_kwh_today = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE zone_number = ?
    """, (1 if new_active else 0, new_last_on, tot_sec, tot_kwh, zone_number))
    conn.commit()
    conn.close()
    
    return get_energy_zones_status()

def set_all_zones(state: bool):
    """Turns all 3 classroom zones ON or OFF manually."""
    # When user clicks master turn on/off, switch mode to manual
    conn = get_db_connection()
    conn.execute("UPDATE energy_settings SET control_mode = 'manual', updated_at = CURRENT_TIMESTAMP")
    conn.commit()
    conn.close()
    
    for zn in [1, 2, 3]:
        toggle_energy_zone(zn, target_state=state, switch_to_manual=False)
    return get_energy_zones_status()

def get_energy_dashboard_metrics():
    """
    Calculates live metrics, active counts, student occupancy, temperature,
    current power, energy consumed, energy saved, and dynamic status message.
    """
    settings = get_energy_settings()
    if settings.get('control_mode') == 'auto':
        sync_automatic_energy_state()
        
    zones = get_energy_zones_status()
    student_count = get_current_student_count()
    temperature = float(settings.get('temperature', 28.0))
    control_mode = settings.get('control_mode', 'auto')
    is_student_override = settings.get('manual_student_override') is not None
    
    current_power_watts = sum(z['current_power_watts'] for z in zones)
    max_power_watts = 795.0 # 9 fans (675W) + 6 lights (120W) = 795 W
    
    active_count = sum(1 for z in zones if z['is_active'])
    total_count = len(zones)
    
    fans_on = sum(z['working_fans'] for z in zones)
    total_fans = sum(z['fans_count'] for z in zones) # 9
    
    lights_on = sum(z['working_lights'] for z in zones)
    total_lights = sum(z['lights_count'] for z in zones) # 6
    
    today_kwh = sum(z['energy_kwh'] for z in zones)
    
    classroom_op_sec = max((z['operating_seconds'] for z in zones), default=0) if zones else 0
    classroom_op_hours = round(classroom_op_sec / 3600.0, 2)
    
    if classroom_op_hours > 0:
        baseline_kwh = round(0.795 * classroom_op_hours, 3)
        if baseline_kwh < today_kwh:
            baseline_kwh = round(today_kwh, 3)
    else:
        baseline_kwh = round(today_kwh, 3)
        
    saved_kwh = max(0.0, round(baseline_kwh - today_kwh, 3))
    
    if baseline_kwh > 0.001:
        saving_percentage = round((saved_kwh / baseline_kwh) * 100.0, 1)
    else:
        saving_percentage = round(((max_power_watts - current_power_watts) / max_power_watts) * 100.0, 1) if max_power_watts > 0 else 0.0
        
    today_cost = round(today_kwh * TARIFF_PER_KWH, 2)
    today_cost_saved = round(saved_kwh * TARIFF_PER_KWH, 2)
    
    # Dynamic Status Message: e.g. "2 Zones Active – 15 Students – 28°C"
    temp_display = int(temperature) if temperature.is_integer() else temperature
    if active_count == 0:
        status_message = f"All Zones Inactive – {student_count} Students – {temp_display}°C"
    else:
        zone_str = f"{active_count} Zone{'s' if active_count != 1 else ''} Active"
        stu_str = f"{student_count} Student{'s' if student_count != 1 else ''}"
        status_message = f"{zone_str} – {stu_str} – {temp_display}°C"
        
    # Informative breakdown for status badge/banner
    if control_mode == 'auto':
        if active_count == 0:
            rule_reason = "Zero students (0); all zones powered down."
        elif active_count == 1:
            rule_reason = "1–10 students; Zone 1 active."
        elif active_count == 2:
            rule_reason = "11–20 students; Zones 1 & 2 active."
        else:
            rule_reason = "21+ students; All 3 zones active."
            
        if temperature < 24.0:
            temp_reason = "Fans OFF (<24°C)"
        elif 24.0 <= temperature <= 27.0:
            temp_reason = "Fans Normal Speed (24–27°C)"
        else:
            temp_reason = "Fans Full Speed (>27°C)"
            
        status_detail = f"AUTO MODE: {rule_reason} • {temp_reason} • {lights_on}/6 Lights ON"
    else:
        status_detail = f"MANUAL MODE: Teacher manual override ({active_count}/3 zones active) • {fans_on}/9 Fans • {lights_on}/6 Lights"
        
    return {
        'control_mode': control_mode,
        'temperature': temperature,
        'student_count': student_count,
        'is_student_override': is_student_override,
        'status_message': status_message,
        'status_detail': status_detail,
        'current_power_watts': round(current_power_watts, 1),
        'current_power_kw': round(current_power_watts / 1000.0, 3),
        'max_power_watts': max_power_watts,
        'max_power_kw': 0.795,
        'active_zones_count': active_count,
        'total_zones_count': total_count,
        'active_zones_ratio': f"{active_count} / {total_count}",
        'fans_on': fans_on,
        'total_fans': total_fans,
        'fans_ratio': f"{fans_on} / {total_fans}",
        'lights_on': lights_on,
        'total_lights': total_lights,
        'lights_ratio': f"{lights_on} / {total_lights}",
        'today_kwh': round(today_kwh, 3),
        'baseline_kwh': round(baseline_kwh, 3),
        'saved_kwh': round(saved_kwh, 3),
        'saving_percentage': saving_percentage,
        'tariff_rate': TARIFF_PER_KWH,
        'today_cost': today_cost,
        'today_cost_saved': today_cost_saved,
        'classroom_op_hours': classroom_op_hours,
        'classroom_op_formatted': format_duration(classroom_op_sec),
        'zones': zones
    }

def get_energy_history(limit: int = 14):
    """Retrieves historical energy logs ordered by date DESC."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM energy_history
    ORDER BY date DESC
    LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


