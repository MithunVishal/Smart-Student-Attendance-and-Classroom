/**
 * Smart Student Attendance and Classroom Utilization System
 * Real-Time Camera Barcode Scanner Engine
 */

class BarcodeScannerEngine {
  constructor() {
    this.video = document.getElementById('scannerVideo');
    this.canvas = document.getElementById('scannerCanvas');
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    
    // UI elements
    this.studentCard = document.getElementById('studentDisplayCard');
    this.emptyState = document.getElementById('emptyScanState');
    this.studentPhoto = document.getElementById('studentPhoto');
    this.studentName = document.getElementById('studentName');
    this.studentRegNo = document.getElementById('studentRegNo');
    this.studentDept = document.getElementById('studentDept');
    this.studentYearSec = document.getElementById('studentYearSec');
    this.studentBarcodeId = document.getElementById('studentBarcodeId');
    this.scanDate = document.getElementById('scanDate');
    this.scanTime = document.getElementById('scanTime');
    this.statusBanner = document.getElementById('actionStatusBanner');
    this.statusText = document.getElementById('actionStatusText');
    this.statusTimeDetails = document.getElementById('actionTimeDetails');
    this.durationBadge = document.getElementById('durationBadge');
    this.cameraSelect = document.getElementById('cameraSelect');
    this.btnToggleCamera = document.getElementById('btnToggleCamera');
    this.liveOccupancyCount = document.getElementById('liveOccupancyCount');
    this.recentScansTbody = document.getElementById('recentScansTbody');
    
    this.stream = null;
    this.isScanning = false;
    this.isProcessingFrame = false;
    this.currentDeviceId = null;
    this.scanIntervalMs = 220; // High responsiveness (approx 4.5 FPS payload)
    
    // Offscreen capture canvas
    this.captureCanvas = document.createElement('canvas');
    this.captureCtx = this.captureCanvas.getContext('2d');
    
    // Web Audio Synthesizer for instant zero-latency chimes
    this.audioCtx = null;
    
    // Client-side debounce tracker to prevent repetitive network spam
    this.lastScannedCode = null;
    this.lastScanTimestamp = 0;
    this.debounceWindowMs = 2000;
    
    this.initAudio();
    this.initCameraDevices();
    this.attachEventListeners();
  }

  initAudio() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) {
      this.audioCtx = new AudioContextClass();
    }
  }

  playChime(type = 'in') {
    if (!this.audioCtx) return;
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
    
    const now = this.audioCtx.currentTime;
    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();
    
    osc.connect(gain);
    gain.connect(this.audioCtx.destination);
    
    if (type === 'in') {
      // Pleasant rising check-in chime (C5 -> E5)
      osc.type = 'sine';
      osc.frequency.setValueAtTime(523.25, now); // C5
      osc.frequency.exponentialRampToValueAtTime(659.25, now + 0.12); // E5
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.35);
    } else if (type === 'out') {
      // Pleasant falling check-out chime (E5 -> C5)
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(659.25, now);
      osc.frequency.exponentialRampToValueAtTime(523.25, now + 0.15);
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.start(now);
      osc.stop(now + 0.4);
    } else {
      // Soft notification beep
      osc.type = 'sine';
      osc.frequency.setValueAtTime(440, now);
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.2);
      osc.start(now);
      osc.stop(now + 0.2);
    }
  }

  async initCameraDevices() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(d => d.kind === 'videoinput');
      
      if (this.cameraSelect) {
        this.cameraSelect.innerHTML = '';
        videoDevices.forEach((device, index) => {
          const opt = document.createElement('option');
          opt.value = device.deviceId;
          opt.text = device.label || `Camera ${index + 1}`;
          this.cameraSelect.appendChild(opt);
        });
        
        if (videoDevices.length > 0) {
          this.currentDeviceId = videoDevices[0].deviceId;
          this.cameraSelect.value = this.currentDeviceId;
        }
      }
      
      // Automatically start camera
      await this.startCamera();
    } catch (err) {
      console.warn("Camera enumeration error:", err);
      // Fallback start
      await this.startCamera();
    }
  }

  attachEventListeners() {
    if (this.cameraSelect) {
      this.cameraSelect.addEventListener('change', (e) => {
        this.currentDeviceId = e.target.value;
        this.startCamera(this.currentDeviceId);
      });
    }
    
    if (this.btnToggleCamera) {
      this.btnToggleCamera.addEventListener('click', () => {
        if (this.isScanning) {
          this.stopCamera();
        } else {
          this.startCamera(this.currentDeviceId);
        }
      });
    }
    
    window.addEventListener('resize', () => this.syncCanvasDimensions());
  }

  syncCanvasDimensions() {
    if (!this.video || !this.canvas) return;
    this.canvas.width = this.video.clientWidth || 640;
    this.canvas.height = this.video.clientHeight || 480;
  }

  async startCamera(deviceId = null) {
    this.stopCamera();
    
    const constraints = {
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: deviceId ? undefined : { ideal: 'environment' }
      },
      audio: false
    };
    
    if (deviceId) {
      constraints.video.deviceId = { exact: deviceId };
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia(constraints);
      this.video.srcObject = this.stream;
      await this.video.play();
      
      this.isScanning = true;
      if (this.btnToggleCamera) {
        this.btnToggleCamera.innerHTML = '<i class="bi bi-pause-circle"></i> Pause Camera';
        this.btnToggleCamera.classList.replace('btn-primary', 'btn-outline-primary');
      }
      
      this.syncCanvasDimensions();
      this.startScanningLoop();
    } catch (err) {
      console.error("Unable to access camera:", err);
      const errBox = document.getElementById('cameraErrorAlert');
      if (errBox) {
        errBox.textContent = `Camera error: ${err.message}. Please check browser camera permissions.`;
        errBox.classList.remove('d-none');
      }
    }
  }

  stopCamera() {
    this.isScanning = false;
    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
    }
    if (this.btnToggleCamera) {
      this.btnToggleCamera.innerHTML = '<i class="bi bi-play-circle"></i> Start Camera';
      this.btnToggleCamera.classList.replace('btn-outline-primary', 'btn-primary');
    }
    this.clearBoundingBox();
  }

  startScanningLoop() {
    const loop = async () => {
      if (!this.isScanning) return;
      
      if (!this.isProcessingFrame && this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        await this.captureAndProcessFrame();
      }
      
      setTimeout(loop, this.scanIntervalMs);
    };
    loop();
  }

  async captureAndProcessFrame() {
    this.isProcessingFrame = true;
    
    try {
      const vWidth = this.video.videoWidth || 640;
      const vHeight = this.video.videoHeight || 480;
      
      // Target 640px wide for optimal OpenCV + pyzbar performance
      const scale = Math.min(1.0, 640 / vWidth);
      const targetW = Math.round(vWidth * scale);
      const targetH = Math.round(vHeight * scale);
      
      this.captureCanvas.width = targetW;
      this.captureCanvas.height = targetH;
      
      this.captureCtx.drawImage(this.video, 0, 0, targetW, targetH);
      const base64Data = this.captureCanvas.toDataURL('image/jpeg', 0.82);
      
      // Send frame to Flask OpenCV + Pyzbar endpoint
      const response = await fetch('/api/scan_frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: base64Data })
      });
      
      if (!response.ok) {
        this.isProcessingFrame = false;
        return;
      }
      
      const result = await response.json();
      this.handleScanResult(result, targetW, targetH);
      
    } catch (err) {
      console.warn("Scan frame transmission error:", err);
    } finally {
      this.isProcessingFrame = false;
    }
  }

  handleScanResult(result, frameW, frameH) {
    if (result.status === 'no_barcode') {
      this.clearBoundingBox();
      return;
    }
    
    // Draw Bounding Box around detected barcode
    if (result.barcode) {
      this.drawBarcodeBoundingBox(result.barcode, frameW, frameH, result.status);
    }
    
    const now = Date.now();
    const barcodeCode = result.barcode_id || (result.barcode && result.barcode.data);
    
    // Check client debounce window
    if (this.lastScannedCode === barcodeCode && (now - this.lastScanTimestamp) < this.debounceWindowMs) {
      return;
    }
    
    this.lastScannedCode = barcodeCode;
    this.lastScanTimestamp = now;
    
    if (result.status === 'success') {
      const action = result.action; // 'CHECK_IN' or 'CHECK_OUT'
      this.playChime(action === 'CHECK_IN' ? 'in' : 'out');
      this.renderStudentInfo(result);
      this.updateNavbarOccupancy(result.current_inside);
      this.prependRecentScan(result);
    } else if (result.status === 'cooldown') {
      this.playChime('notice');
      this.renderCooldownInfo(result);
    } else if (result.status === 'not_found') {
      this.playChime('notice');
      this.renderNotFoundInfo(result);
    }
  }

  drawBarcodeBoundingBox(barcode, frameW, frameH, status) {
    if (!this.ctx || !this.canvas) return;
    this.syncCanvasDimensions();
    
    const canvasW = this.canvas.width;
    const canvasH = this.canvas.height;
    const scaleX = canvasW / frameW;
    const scaleY = canvasH / frameH;
    
    this.ctx.clearRect(0, 0, canvasW, canvasH);
    
    const polygon = barcode.polygon || [];
    const color = status === 'success' ? '#10b981' : '#3b82f6';
    
    if (polygon && polygon.length >= 4) {
      this.ctx.beginPath();
      this.ctx.moveTo(polygon[0].x * scaleX, polygon[0].y * scaleY);
      for (let i = 1; i < polygon.length; i++) {
        this.ctx.lineTo(polygon[i].x * scaleX, polygon[i].y * scaleY);
      }
      this.ctx.closePath();
      
      this.ctx.lineWidth = 4;
      this.ctx.strokeStyle = color;
      this.ctx.shadowColor = color;
      this.ctx.shadowBlur = 12;
      this.ctx.stroke();
      
      // Draw corner accent dots
      this.ctx.fillStyle = '#ffffff';
      polygon.forEach(pt => {
        this.ctx.beginPath();
        this.ctx.arc(pt.x * scaleX, pt.y * scaleY, 5, 0, Math.PI * 2);
        this.ctx.fill();
      });
      
    } else if (barcode.rect) {
      const r = barcode.rect;
      this.ctx.lineWidth = 4;
      this.ctx.strokeStyle = color;
      this.ctx.shadowColor = color;
      this.ctx.shadowBlur = 12;
      this.ctx.strokeRect(r.x * scaleX, r.y * scaleY, r.w * scaleX, r.h * scaleY);
    }
  }

  clearBoundingBox() {
    if (this.ctx && this.canvas) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  renderStudentInfo(result) {
    const student = result.student;
    const attendance = result.attendance;
    const isCheckIn = result.action === 'CHECK_IN';
    
    if (this.emptyState) this.emptyState.classList.add('d-none');
    if (this.studentCard) this.studentCard.classList.remove('d-none');
    
    // Populate details
    if (this.studentPhoto) {
      this.studentPhoto.src = `/static/${student.photo_path}`;
      this.studentPhoto.alt = student.student_name;
    }
    if (this.studentName) this.studentName.textContent = student.student_name;
    if (this.studentRegNo) this.studentRegNo.textContent = student.register_number;
    if (this.studentDept) this.studentDept.textContent = student.department;
    if (this.studentYearSec) this.studentYearSec.textContent = `${student.year} • Section ${student.section}`;
    if (this.studentBarcodeId) this.studentBarcodeId.textContent = student.barcode_id;
    
    const now = new Date();
    if (this.scanDate) {
      this.scanDate.textContent = now.toLocaleDateString('en-US', {
        weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'
      });
    }
    if (this.scanTime) {
      this.scanTime.textContent = now.toLocaleTimeString('en-US');
    }
    
    // Status Banner
    if (this.statusBanner) {
      this.statusBanner.className = `action-status-banner ${isCheckIn ? 'check-in' : 'check-out'}`;
    }
    if (this.statusText) {
      this.statusText.innerHTML = isCheckIn 
        ? `<i class="bi bi-box-arrow-in-right fs-5"></i> <span>CHECKED IN (Present)</span>`
        : `<i class="bi bi-box-arrow-right fs-5"></i> <span>CHECKED OUT</span>`;
    }
    
    if (this.statusTimeDetails) {
      if (isCheckIn) {
        this.statusTimeDetails.textContent = `IN Time: ${attendance.in_time}`;
      } else {
        this.statusTimeDetails.textContent = `IN: ${attendance.in_time}  |  OUT: ${attendance.out_time}`;
      }
    }
    
    if (this.durationBadge) {
      if (!isCheckIn && attendance.duration_formatted) {
        this.durationBadge.textContent = `Duration: ${attendance.duration_formatted}`;
        this.durationBadge.classList.remove('d-none');
      } else {
        this.durationBadge.classList.add('d-none');
      }
    }
  }

  renderCooldownInfo(result) {
    if (this.statusBanner) {
      this.statusBanner.className = 'action-status-banner cooldown';
    }
    if (this.statusText) {
      this.statusText.innerHTML = `<i class="bi bi-hourglass-split fs-5"></i> <span>COOLDOWN ACTIVE</span>`;
    }
    if (this.statusTimeDetails) {
      this.statusTimeDetails.textContent = result.message;
    }
  }

  renderNotFoundInfo(result) {
    if (this.emptyState) this.emptyState.classList.add('d-none');
    if (this.studentCard) this.studentCard.classList.remove('d-none');
    
    if (this.studentName) this.studentName.textContent = "Unregistered Barcode";
    if (this.studentRegNo) this.studentRegNo.textContent = result.barcode_id || "N/A";
    if (this.studentDept) this.studentDept.textContent = "Unknown Department";
    if (this.studentYearSec) this.studentYearSec.textContent = "Please add student to database";
    
    if (this.statusBanner) {
      this.statusBanner.className = 'action-status-banner cooldown';
    }
    if (this.statusText) {
      this.statusText.innerHTML = `<i class="bi bi-exclamation-triangle fs-5"></i> <span>NOT REGISTERED</span>`;
    }
    if (this.statusTimeDetails) {
      this.statusTimeDetails.textContent = result.message;
    }
  }

  updateNavbarOccupancy(count) {
    if (count !== undefined) {
      if (this.liveOccupancyCount) {
        this.liveOccupancyCount.textContent = count;
      }
      const navBadge = document.getElementById('navbarRoomCount');
      if (navBadge) {
        navBadge.textContent = count;
      }
    }
  }

  prependRecentScan(result) {
    if (!this.recentScansTbody) return;
    
    const student = result.student;
    const att = result.attendance;
    const isInside = att.status === 'Inside';
    
    const tr = document.createElement('tr');
    tr.style.animation = 'fadeIn 0.4s ease';
    tr.innerHTML = `
      <td>
        <img src="/static/${student.photo_path}" class="table-student-avatar" alt="Avatar">
      </td>
      <td>
        <div class="fw-bold text-dark">${student.student_name}</div>
        <div class="small text-muted">${student.register_number}</div>
      </td>
      <td><span class="badge bg-light text-dark border">${student.department}</span></td>
      <td><span class="fw-semibold">${att.in_time}</span></td>
      <td>${att.out_time || '<span class="text-muted">-</span>'}</td>
      <td><span class="fw-semibold text-primary">${att.duration_formatted || '0s'}</span></td>
      <td>
        <span class="${isInside ? 'badge-inside' : 'badge-exited'}">
          <span class="pulse-dot ${isInside ? 'green' : ''}"></span>
          ${att.status}
        </span>
      </td>
    `;
    
    this.recentScansTbody.insertBefore(tr, this.recentScansTbody.firstChild);
    
    // Keep max 8 rows
    while (this.recentScansTbody.children.length > 8) {
      this.recentScansTbody.removeChild(this.recentScansTbody.lastChild);
    }
  }
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  window.scannerEngine = new BarcodeScannerEngine();
});
