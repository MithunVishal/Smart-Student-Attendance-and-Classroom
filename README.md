# Smart Student Attendance and Classroom Utilization System

An intelligent web application that uses laptop or mobile webcams to **scan student ID card barcodes in real time**, automatically logs student **IN Time**, **OUT Time**, and **Duration**, and computes **Classroom Occupancy & Utilization** analytics.

---

## 🌟 Key Features

1. **Camera-Based Real-Time Barcode Scanning**
   - Direct webcam/camera access via `navigator.mediaDevices.getUserMedia`.
   - Continuous scanning pipeline powered by **OpenCV** and **Pyzbar**.
   - **Low-light & Motion Optimization**: OpenCV CLAHE (Contrast Limited Adaptive Histogram Equalization) and adaptive filtering ensure detection even in dim or uneven lighting.
   - **Dynamic Bounding Box**: Draws live glowing green bounding polygons and corner brackets over the barcode in the camera feed.
   - **Audio Chime**: Zero-latency synthesized audio feedback on scan (Web Audio API).
   - **Anti-Flutter Cooldown**: Intelligent 5-second cooldown prevents repeated accidental triggers on the same presentation of a card.

2. **Automated Attendance Lifecycle**
   - **1st Scan**: Marks student **Present**, saves **IN Time**, sets status to **Inside**.
   - **2nd Scan**: Records **OUT Time**, computes **Duration** ($\text{OUT Time} - \text{IN Time}$), updates status to **Exited**.
   - Displays real-time student verification card with Student Photo, Full Name, Register Number, Department, Year, Section, and Time details.

3. **Classroom Utilization & Occupancy Tracking**
   - Monitors live room capacity (Room 402 - Smart Computing Lab, 60 Seats).
   - Dynamic utilization bar with safety threshold alerts (<60% optimal, 60-85% high, >85% critical).
   - Department-wise attendance breakdown (Doughnut Chart).
   - Hourly student traffic curve (Line Chart).

4. **Student Database & ID Card Generator**
   - Comprehensive student registry (Name, Register Number, Department, Year, Section, Photo, Barcode ID).
   - Add, edit, and delete student records with photo uploads or auto-generated color avatars.
   - **Instant ID Card Generation**: Generates high-resolution **Code128 barcodes** using `python-barcode`.
   - **Printable ID Cards**: Pre-designed digital ID badges ready to print or display on a smartphone screen for immediate camera scanning tests.

5. **Attendance Audit Table**
   - Live searchable attendance table.
   - Filter by date, department, and status (Inside / Exited / All).
   - Real-time status badges with pulsing indicators.

6. **Multi-Format Export & Reports**
   - Daily, Weekly (7 days), and Monthly (30 days) reports.
   - Export to **Microsoft Excel (`.xlsx`)** with styled headers and summary rows via `openpyxl`.
   - Export to **CSV (`.csv`)** for database interoperability.
   - Export to **PDF (`.pdf`)** with institutional letterhead and formatted tables via `reportlab`.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python Flask, Werkzeug |
| **Barcode Engine** | OpenCV (`cv2`), Pyzbar, Python-Barcode (Code128) |
| **Database** | SQLite (with foreign key enforcement) |
| **Frontend** | HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3, Bootstrap Icons, Chart.js |
| **Audio Synthesizer**| Web Audio API (zero latency synthetic chime) |
| **Reporting** | OpenPyXL (Excel), ReportLab (PDF), Python standard `csv` |

---

## 🚀 Quick Start Guide

### 1. Requirements
Ensure Python 3.8+ is installed on your machine. All required packages are already configured in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 2. Start the Application
Run the Flask server:
```bash
python app.py
```
The server will start at:
```
http://127.0.0.1:5000
```

### 3. Log In
Open your browser and navigate to `http://127.0.0.1:5000/login`.
- **Username**: `admin`
- **Password**: `admin123`
*(A convenient "Auto-Fill" button is provided on the login page for rapid testing)*

---

## 📷 How to Test Real-Time Camera Barcode Scanning

1. Navigate to **Printable ID Cards** (`/id-cards`) in the sidebar, or click **ID Card** next to any student in the **Student Directory**.
2. Either:
   - Display the ID card / barcode on your **smartphone screen**, or
   - Print out one of the test badges.
3. Open the **Live Barcode Scanner** (`/scanner`) in another browser tab or on your laptop.
4. Allow camera permissions when prompted.
5. Hold the barcode in front of your webcam:
   - The green bounding box will immediately lock onto the barcode.
   - An audio chime will play.
   - The student's photo, name, department, register number, and **CHECKED IN** status will appear in real time.
6. Present the same card again after 5 seconds:
   - The system records **CHECKED OUT** and displays the calculated **Duration** spent in the classroom!
7. Check the **Dashboard** and **Attendance Records** to see the live updates reflected instantly.
