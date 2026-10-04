# Smart Student Attendance & Classroom Energy Management System

An intelligent web application that combines **real-time camera-based student ID card barcode scanning** for automatic attendance tracking with **smart classroom 3-zone energy management and power efficiency monitoring**.

---

## 🌟 Key Features

### 1. Camera-Based Real-Time Barcode Scanning
- Direct webcam/camera access via `navigator.mediaDevices.getUserMedia` with mobile front/rear camera switcher.
- Dual-engine scanning pipeline powered by **OpenCV**, **ZXing-cpp**, and **Pyzbar**.
- **Physical ID Card Scanning**: Tuned for student physical ID card barcodes (Code39 / Code128 format).
- **Auto-Detect From Uploaded Images**: Instant `/api/decode_barcode_image` endpoint to scan uploaded student ID card photos.
- **Dynamic Bounding Box**: Draws live glowing green bounding polygons and corner brackets over the barcode in the camera feed.
- **Audio Chime**: Zero-latency synthesized audio feedback on scan (Web Audio API).
- **Anti-Flutter Cooldown**: Intelligent 5-second cooldown prevents repeated accidental triggers.

### 2. Automated Attendance Lifecycle
- **1st Scan**: Marks student **Present**, saves **IN Time**, sets status to **Inside**.
- **2nd Scan**: Records **OUT Time**, computes **Duration** ($\text{OUT Time} - \text{IN Time}$), updates status to **Exited**.
- Displays real-time student verification card with Student Photo, Full Name, Register Number, Department (**Artificial Intelligence and Data Science**, etc.), Year, Section, and Time details.

### 3. ⚡ Classroom Energy Management (New)
The classroom is divided into **3 electrical zones**:
* **Zone 1 (Front Row / Lectern)**: 3 Fans (75 W each) + 2 Lights (20 W each) = **265 W**
* **Zone 2 (Middle Classroom)**: 3 Fans (75 W each) + 2 Lights (20 W each) = **265 W**
* **Zone 3 (Rear Classroom)**: 3 Fans (75 W each) + 2 Lights (20 W each) = **265 W**

- **Manual ON/OFF Controls**: Individual toggle buttons for each zone, plus master "Turn All ON" and "Turn All OFF".
- **Live Metrics Per Zone**:
  - Operational Status: **ON / OFF**
  - Number of fans and lights working
  - Current power consumption in Watts ($265\,\text{W}$ when ON, $0\,\text{W}$ when OFF)
  - Operating runtime counter ($HH:MM:SS$)
  - Energy consumed in kWh ($E = P \times t / 1000$)
- **Energy Dashboard**:
  - **Current Power Consumption** (W and kW)
  - **Today's Energy Consumption** (kWh)
  - **Energy Saved** (kWh) based on maximum reference (all 3 zones ON = 795 W baseline)
  - **Estimated Electricity Cost** (₹) based on standard institutional tariff (₹8.00/kWh)
  - **Active Zones Count** (e.g., $2 / 3$ Zones)
  - **Energy Saving Percentage** ($\%$)
- **Energy History & Audit Log**:
  - Table of daily classroom electricity consumption, reference baselines, energy saved, and cost savings.
  - Interactive Chart.js analytics for daily consumption vs. baseline savings trend.

### 4. Student Management & Multi-Format Reports
- Comprehensive student directory with search and filtering by department (including **Artificial Intelligence and Data Science**).
- Export attendance records to **Excel (`.xlsx`)**, **CSV (`.csv`)**, and **PDF (`.pdf`)**.

---

## 🚀 Two Easy Ways to Run the Application

### Option 1: Run in VS Code (Editable Code & Debugging)
1. Open this project folder in **Visual Studio Code**:
   - Open VS Code $\rightarrow$ `File` $\rightarrow$ `Open Folder...` $\rightarrow$ Select this project folder (`e:\Iris` or `E:\id card bar code`).
2. **Press F5** to start debugging (or go to `Run` $\rightarrow$ `Start Debugging`).
   - The predefined `.vscode/launch.json` will automatically launch the Flask web server in your integrated terminal.
   - Alternatively, press **`Ctrl+Shift+B`** to run the build task.
3. Or run directly from the VS Code integrated terminal (`Ctrl+\``):
   ```bash
   python app.py
   ```
4. Open your browser at:
   ```
   http://127.0.0.1:5000
   ```

### Option 2: Double-Click from Folder (1-Click Launch)
1. Open the project folder in **Windows File Explorer**.
2. **Double-click on `START_APP.bat`**:
   - It will check your Python installation.
   - It starts the Flask web server.
   - It automatically launches your default web browser to `http://127.0.0.1:5000`.

---

## 🔐 Login Credentials
- **Username**: `admin`
- **Password**: `admin123`
*(A convenient "Auto-Fill" button is provided on the login page for quick access)*

---

## 🧪 Running Tests
To run the automated test suite covering barcode decoding, attendance lifecycle, and energy management:
```bash
python test_app.py
```
Output:
```
Ran 5 tests in 0.790s - OK
```
