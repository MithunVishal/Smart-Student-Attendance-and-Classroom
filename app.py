import os
import io
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, send_file, Response
)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

from config import Config
from database import (
    init_db, get_db_connection, get_dashboard_stats,
    get_attendance_records, get_all_students, record_attendance_scan,
    create_sample_avatar
)
from scanner import decode_base64_image, scan_barcodes_from_image, decode_barcode_from_file_bytes
from reports import export_to_csv, export_to_excel, export_to_pdf

app = Flask(__name__)
app.config.from_object(Config)

# Ensure DB and columns exist
init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("Please log in to access this system.", "warning")
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Context processor for global template variables
@app.context_processor
def inject_globals():
    return {
        'current_year': datetime.now().year,
        'today_date': date.today().strftime('%Y-%m-%d'),
        'current_time_str': datetime.now().strftime('%H:%M:%S'),
        'logged_in': session.get('logged_in', False),
        'admin_name': session.get('admin_name', 'Admin')
    }

# ==========================================
# AUTHENTICATION ROUTES
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['admin_name'] = user['full_name']
            session['username'] = user['username']
            flash(f"Welcome back, {user['full_name']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password. (Hint: admin / admin123)", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('login'))

# ==========================================
# DASHBOARD
# ==========================================

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    selected_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    stats = get_dashboard_stats(selected_date)
    return render_template('dashboard.html', stats=stats, selected_date=selected_date)

@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    selected_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    stats = get_dashboard_stats(selected_date)
    return jsonify(stats)

# ==========================================
# REAL-TIME SCANNER & API
# ==========================================

@app.route('/scanner')
@login_required
def scanner():
    today_str = date.today().strftime('%Y-%m-%d')
    stats = get_dashboard_stats(today_str)
    return render_template('scanner.html', stats=stats)

@app.route('/api/scan_frame', methods=['POST'])
@login_required
def api_scan_frame():
    """
    Receives base64 camera frame from client:
    1. Preprocesses image via OpenCV.
    2. Decodes actual physical barcode via Pyzbar / ZXing.
    3. Finds match in student database.
    4. Handles IN / OUT / Cooldown logic.
    5. Returns student details, exact scanned barcode number, bounding box & status.
    """
    data = request.get_json(silent=True) or {}
    image_data = data.get('image')
    
    if not image_data:
        return jsonify({'status': 'error', 'message': 'No image frame received'}), 400
        
    try:
        image = decode_base64_image(image_data)
        if image is None:
            return jsonify({'status': 'error', 'message': 'Failed to decode image frame'}), 400
            
        detected_barcodes = scan_barcodes_from_image(image)
        
        if not detected_barcodes:
            return jsonify({'status': 'no_barcode'})
            
        # Primary barcode detected from student ID card
        primary_barcode = detected_barcodes[0]
        barcode_id = primary_barcode['data'].strip()
        barcode_type = primary_barcode['type']
        
        # Process attendance in database
        result = record_attendance_scan(barcode_id)
        
        # Attach detected geometric coordinates and decoded number
        result['barcode'] = {
            'data': barcode_id,
            'type': barcode_type,
            'rect': primary_barcode.get('rect'),
            'polygon': primary_barcode.get('polygon')
        }
        result['decoded_barcode_id'] = barcode_id
        
        # Fetch updated quick room stats
        today_str = date.today().strftime('%Y-%m-%d')
        conn = get_db_connection()
        inside_count = conn.execute(
            "SELECT COUNT(*) as count FROM attendance WHERE date = ? AND status = 'Inside'",
            (today_str,)
        ).fetchone()['count']
        present_count = conn.execute(
            "SELECT COUNT(DISTINCT student_id) as count FROM attendance WHERE date = ?",
            (today_str,)
        ).fetchone()['count']
        conn.close()
        
        result['current_inside'] = inside_count
        result['present_today'] = present_count
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/decode_barcode_image', methods=['POST'])
@login_required
def api_decode_barcode_image():
    """
    Scans a manually uploaded barcode image / ID card photo and returns the exact decoded barcode number.
    Used for instant auto-filling when adding or editing a student.
    """
    file = request.files.get('barcode_image')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
        
    try:
        file_bytes = file.read()
        res = decode_barcode_from_file_bytes(file_bytes)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# STUDENT MANAGEMENT
# ==========================================

@app.route('/students', methods=['GET', 'POST'])
@login_required
def students():
    conn = get_db_connection()
    
    if request.method == 'POST':
        student_name = request.form.get('student_name', '').strip()
        register_number = request.form.get('register_number', '').strip().upper()
        department = request.form.get('department', '').strip()
        year = request.form.get('year', '').strip()
        section = request.form.get('section', '').strip().upper()
        barcode_id = request.form.get('barcode_id', '').strip()
        
        if not (student_name and register_number and department and year and section):
            flash("Please fill in all required student details.", "danger")
            return redirect(url_for('students'))
            
        # Handle Barcode Image Upload & Auto-Scan
        barcode_image_file = request.files.get('barcode_image')
        barcode_image_path = None
        
        if barcode_image_file and barcode_image_file.filename:
            raw_bytes = barcode_image_file.read()
            filename = secure_filename(f"card_{register_number}_{barcode_image_file.filename}")
            save_path = os.path.join(Config.BARCODES_UPLOAD_FOLDER, filename)
            with open(save_path, 'wb') as f:
                f.write(raw_bytes)
            barcode_image_path = f"uploads/barcodes/{filename}"
            
            # Automatically scan barcode from this uploaded card image if barcode_id was not entered
            if not barcode_id:
                scan_res = decode_barcode_from_file_bytes(raw_bytes)
                if scan_res.get('success'):
                    barcode_id = scan_res['barcode_id']
                    
        if not barcode_id:
            flash("Could not detect barcode from uploaded image. Please enter the Barcode ID manually.", "warning")
            conn.close()
            return redirect(url_for('students'))
            
        # Check uniqueness
        existing = conn.execute(
            "SELECT id FROM students WHERE register_number = ? OR UPPER(barcode_id) = UPPER(?)",
            (register_number, barcode_id)
        ).fetchone()
        
        if existing:
            flash(f"A student with Register Number '{register_number}' or Barcode ID '{barcode_id}' already exists.", "danger")
            conn.close()
            return redirect(url_for('students'))
            
        # Handle Photo Upload
        photo_file = request.files.get('photo')
        photo_path = None
        
        if photo_file and photo_file.filename:
            filename = secure_filename(f"{register_number}_{photo_file.filename}")
            filepath = os.path.join(Config.AVATARS_FOLDER, filename)
            photo_file.save(filepath)
            photo_path = f"uploads/avatars/{filename}"
        else:
            photo_path = create_sample_avatar(student_name, (30, 64, 175))
            
        # Save to database (NO synthetic barcode generated!)
        conn.execute("""
        INSERT INTO students (student_name, register_number, department, year, section, photo_path, barcode_id, barcode_image_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (student_name, register_number, department, year, section, photo_path, barcode_id, barcode_image_path))
        conn.commit()
        conn.close()
        
        flash(f"Student '{student_name}' ({register_number}) registered successfully with Barcode ID: {barcode_id}!", "success")
        return redirect(url_for('students'))
        
    search = request.args.get('search', '')
    department_filter = request.args.get('department', 'All')
    all_students = get_all_students(search=search, department=department_filter)
    conn.close()
    
    return render_template('students.html', students=all_students, search=search, selected_dept=department_filter)

@app.route('/students/edit/<int:student_id>', methods=['POST'])
@login_required
def edit_student(student_id):
    student_name = request.form.get('student_name', '').strip()
    register_number = request.form.get('register_number', '').strip().upper()
    department = request.form.get('department', '').strip()
    year = request.form.get('year', '').strip()
    section = request.form.get('section', '').strip().upper()
    barcode_id = request.form.get('barcode_id', '').strip()
    
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        flash("Student not found.", "danger")
        conn.close()
        return redirect(url_for('students'))
        
    photo_file = request.files.get('photo')
    photo_path = student['photo_path']
    if photo_file and photo_file.filename:
        filename = secure_filename(f"{register_number}_{photo_file.filename}")
        filepath = os.path.join(Config.AVATARS_FOLDER, filename)
        photo_file.save(filepath)
        photo_path = f"uploads/avatars/{filename}"
        
    # Handle barcode image update
    barcode_image_file = request.files.get('barcode_image')
    barcode_image_path = student['barcode_image_path']
    if barcode_image_file and barcode_image_file.filename:
        raw_bytes = barcode_image_file.read()
        filename = secure_filename(f"card_{register_number}_{barcode_image_file.filename}")
        save_path = os.path.join(Config.BARCODES_UPLOAD_FOLDER, filename)
        with open(save_path, 'wb') as f:
            f.write(raw_bytes)
        barcode_image_path = f"uploads/barcodes/{filename}"
        
        # Auto scan if barcode_id was empty
        if not barcode_id:
            scan_res = decode_barcode_from_file_bytes(raw_bytes)
            if scan_res.get('success'):
                barcode_id = scan_res['barcode_id']
                
    if not barcode_id:
        barcode_id = student['barcode_id']
        
    conn.execute("""
    UPDATE students
    SET student_name = ?, register_number = ?, department = ?, year = ?, section = ?, barcode_id = ?, barcode_image_path = ?, photo_path = ?
    WHERE id = ?
    """, (student_name, register_number, department, year, section, barcode_id, barcode_image_path, photo_path, student_id))
    conn.commit()
    conn.close()
    
    flash(f"Student '{student_name}' updated successfully.", "success")
    return redirect(url_for('students'))

@app.route('/students/delete/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student:
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
        flash(f"Student '{student['student_name']}' has been deleted.", "info")
    conn.close()
    return redirect(url_for('students'))

# ==========================================
# ATTENDANCE RECORDS
# ==========================================

@app.route('/attendance')
@login_required
def attendance():
    target_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    department = request.args.get('department', 'All')
    status = request.args.get('status', 'All')
    search = request.args.get('search', '')
    
    records = get_attendance_records(
        target_date=target_date if target_date else None,
        department=department,
        status=status,
        search=search
    )
    
    return render_template(
        'attendance.html',
        records=records,
        selected_date=target_date,
        selected_dept=department,
        selected_status=status,
        search=search
    )

# ==========================================
# REPORTS & EXPORTS
# ==========================================

@app.route('/reports')
@login_required
def reports():
    report_type = request.args.get('report_type', 'daily')
    dept_filter = request.args.get('department', 'All')
    today = date.today()
    
    if report_type == 'weekly':
        start_date = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
        date_label = f"Last 7 Days ({start_date} to {end_date})"
    elif report_type == 'monthly':
        start_date = (today - timedelta(days=30)).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
        date_label = f"Last 30 Days ({start_date} to {end_date})"
    else:  # Daily
        report_type = 'daily'
        req_date = request.args.get('date') or today.strftime('%Y-%m-%d')
        start_date = req_date
        end_date = req_date
        date_label = f"Date: {start_date}"
        
    conn = get_db_connection()
    query = """
    SELECT a.*, s.student_name, s.register_number, s.department, s.year, s.section, s.photo_path, s.barcode_id
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE a.date BETWEEN ? AND ?
    """
    params = [start_date, end_date]
    if dept_filter and dept_filter != 'All':
        query += " AND s.department = ?"
        params.append(dept_filter)
        
    query += " ORDER BY a.date DESC, a.in_time DESC"
    records = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    
    # Calculate Summary Metrics
    total_sessions = len(records)
    unique_students = len(set(r['register_number'] for r in records))
    inside_count = sum(1 for r in records if r['status'] == 'Inside')
    exited_count = sum(1 for r in records if r['status'] == 'Exited')
    
    total_duration_sec = sum(r.get('duration_seconds', 0) for r in records if r.get('duration_seconds'))
    avg_duration_min = round(total_duration_sec / max(1, exited_count) / 60, 1) if exited_count > 0 else 0
    
    summary = {
        'total_sessions': total_sessions,
        'unique_students': unique_students,
        'inside_count': inside_count,
        'exited_count': exited_count,
        'avg_duration_min': avg_duration_min
    }
    
    return render_template(
        'reports.html',
        records=records,
        summary=summary,
        report_type=report_type,
        date_label=date_label,
        start_date=start_date,
        end_date=end_date,
        selected_dept=dept_filter
    )

@app.route('/reports/export/<format_type>')
@login_required
def export_report(format_type):
    report_type = request.args.get('report_type', 'daily')
    start_date = request.args.get('start_date', date.today().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', start_date)
    dept_filter = request.args.get('department', 'All')
    
    conn = get_db_connection()
    query = """
    SELECT a.*, s.student_name, s.register_number, s.department, s.year, s.section, s.barcode_id
    FROM attendance a
    JOIN students s ON a.student_id = s.id
    WHERE a.date BETWEEN ? AND ?
    """
    params = [start_date, end_date]
    if dept_filter and dept_filter != 'All':
        query += " AND s.department = ?"
        params.append(dept_filter)
        
    query += " ORDER BY a.date DESC, a.in_time DESC"
    records = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    date_label = f"{start_date} to {end_date}" if start_date != end_date else start_date
    
    if format_type == 'csv':
        csv_io = export_to_csv(records)
        return Response(
            csv_io.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=Attendance_Report_{report_type}_{timestamp}.csv"}
        )
    elif format_type == 'excel':
        excel_io = export_to_excel(records, report_type=report_type.capitalize(), date_label=date_label)
        return send_file(
            excel_io,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"Attendance_Report_{report_type}_{timestamp}.xlsx"
        )
    elif format_type == 'pdf':
        pdf_io = export_to_pdf(records, report_type=report_type.capitalize(), date_label=date_label)
        return send_file(
            pdf_io,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"Attendance_Report_{report_type}_{timestamp}.pdf"
        )
    else:
        flash("Invalid export format specified.", "danger")
        return redirect(url_for('reports'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1')
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
