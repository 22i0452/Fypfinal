const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

let ws = null;
let isRecording = false;
let pendingRecordingStart = false;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let captureSink = null;
let captureSampleRate = 16000;
let durationInterval = null;
let durationSec = 0;
let allPatients = [];
let doctorAppointments = [];
let filteredPatients = [];
let selectedPatient = null;
let diarizedTranscript = [];
let fullTranscript = [];
let generatedSoap = null;
let soapDraftTouched = false;
let soapSaveBusy = false;
let soapLastSavedNoteId = "";
let soapSectionEditing = {};
let soapSectionSnapshots = {};
let savedNotes = [];
let selectedNoteId = "";
let notesFilterPatientId = "";
let notesSearchQuery = "";
let transcriptMode = "urdu";
let assistantMessages = [];
let assistantBusy = false;
let authMode = "login";
let currentUser = { name: "Shahzaib", org: "Nectar", email: "" };
let activeWorkflow = null;
let activeEncounter = null;
let activeAppointment = null;
let activeChallengeId = "";
let appointmentConfiguration = null;
let consentDecisions = null;
let generatedNoteState = "";
let clinicalTemplates = [];
let selectedTemplateId = "TPL-GP-01";
let previsitSummary = null;
let previsitBusy = false;
let highlightedEvidenceIds = [];
let afterVisitSummaries = {};
let developmentQuickStartEnabled = false;
let developmentQuickStartBusy = false;
let intakeCorrectionSnapshot = null;
let codingNoteId = "";
let codingSuggestions = [];
let codingBusy = false;
let codingAutoGenerate = false;

window.addEventListener("DOMContentLoaded", async () => {
  const authenticated = await initializeAuth();
  if (!authenticated) return;
  greetUser();
  renderTranscript();
  renderSoapEmptyState();
  renderNoteDetail(null);
  renderPatientAssistant();
  await Promise.all([
    fetchPatients(),
    fetchDoctorQueue(),
    fetchNotes(),
    fetchClinicalTemplates(),
    fetchWorkspaceCapabilities(),
  ]);
  renderSelectedPatient();
  connectWebSocket();
  await restoreLastVisit();
  studioIcons();
  window.setInterval(refreshDashboardQueues, 30000);
});

function greetUser() {
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const displayName = currentUser.name || "Clinician";
  const orgLabel = "";
  document.getElementById("greetingText").innerHTML = `${greet} <strong>${escHtml(displayName)}</strong>${escHtml(orgLabel)}`;
  document.querySelector(".avatar-btn").textContent = getInitials(displayName || "MA");
}

async function initializeAuth() {
  try {
    const response = await fetch("/api/auth/me", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Authentication required");
    const user = await response.json();
    currentUser = {
      name: user.full_name || "Clinician",
      org: "MedFlowAI Demo Clinic",
      email: user.email || "",
      role: user.role || "DOCTOR",
      practitionerId: user.practitioner_id || "",
    };
    unlockWorkspace();
    return true;
  } catch {
    // Keep the embedded login shell hidden and leave immediately. Calling
    // lockWorkspace() here briefly painted the old login UI before redirect.
    document.body.classList.add("auth-booting");
    document.body.classList.remove("auth-ready");
    location.replace("/consultation/login");
    return false;
  }
}

function setAuthMode(mode) {
  authMode = mode === "signup" ? "signup" : "login";
  document.getElementById("loginTabBtn").classList.toggle("active", authMode === "login");
  document.getElementById("signupTabBtn").classList.toggle("active", authMode === "signup");
  document.getElementById("loginPanel").classList.toggle("active", authMode === "login");
  document.getElementById("signupPanel").classList.toggle("active", authMode === "signup");
  document.getElementById("authHeading").textContent = authMode === "login" ? "Login" : "Create Account";
  document.getElementById("authSubheading").textContent = authMode === "login"
    ? "Sign in to continue to your Medflow AI workspace."
    : "Set up a local access profile for this Medflow AI workspace.";
}

function lockWorkspace() {
  document.body.classList.add("auth-locked");
  document.body.classList.remove("auth-ready", "auth-booting");
}

function unlockWorkspace() {
  document.body.classList.remove("auth-locked", "auth-booting");
  document.body.classList.add("auth-ready");
}

async function handleSignup(event) {
  event.preventDefault();
  const name = document.getElementById("signupName").value.trim();
  const org = document.getElementById("signupOrg").value.trim();
  const email = document.getElementById("signupEmail").value.trim().toLowerCase();
  const password = document.getElementById("signupPassword").value;
  const confirm = document.getElementById("signupConfirm").value;

  if (!name || !email || !password) {
    showToast("Complete all required fields before creating the account.", "error");
    return;
  }
  if (password.length < 8) {
    showToast("Use at least 8 characters for the password.", "error");
    return;
  }
  if (password !== confirm) {
    showToast("The password confirmation does not match.", "error");
    return;
  }

  try {
    const response = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name: name, email, password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to create the account."));
    showToast("Account created. Sign in to continue.");
    document.getElementById("loginEmail").value = email;
    setAuthMode("login");
  } catch (error) {
    showToast(error.message || "Unable to create the account.", "error");
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const email = document.getElementById("loginEmail").value.trim().toLowerCase();
  const password = document.getElementById("loginPassword").value;
  if (!email || !password) {
    showToast("Enter your email and password to continue.", "error");
    return;
  }

  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Invalid email or password."));
    location.replace("/workspace");
  } catch (error) {
    showToast(error.message || "Unable to sign in.", "error");
  }
}

function setActiveNav(view) {
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
}

function setView(view) {
  if (view !== "visit" && !canLeaveVisit()) return;
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  const map = {
    dashboard: "dashboardView",
    visit: "visitView",
    notes: "notesView",
    coding: "codingView",
    assistant: "assistantView",
  };
  const target = document.getElementById(map[view]);
  if (target) target.classList.add("active");
  setActiveNav(view);
}

function showDashboard() {
  setView("dashboard");
  document.getElementById("eyebrowText").textContent = "Today’s workspace";
}

function showVisitWorkspace() {
  setView("visit");
  document.getElementById("eyebrowText").textContent = selectedPatient ? `Patient workspace: ${selectedPatient.name || "Unknown"}` : "Capture workspace";
}

function showCodingWorkspace(options = {}) {
  if (!canLeaveVisit()) return;
  const preferredNoteId = options.noteId || soapLastSavedNoteId || selectedNoteId || "";
  if (preferredNoteId) codingNoteId = preferredNoteId;
  codingAutoGenerate = Boolean(options.autoGenerate);
  setView("coding");
  document.getElementById("eyebrowText").textContent = `Coding: ${resolveCodingNote()?.patient_name || "Select a note"}`;
  renderCodingWorkspace();
  if (codingNoteId) {
    loadCodingSuggestions(codingNoteId).then(() => {
      if (codingAutoGenerate && !codingSuggestions.length) {
        generateCodingSuggestions(false);
      }
      codingAutoGenerate = false;
    });
  }
}

function openCodingFromNote(autoGenerate = true) {
  const noteId = soapLastSavedNoteId || selectedNoteId || codingNoteId;
  if (!noteId) {
    showToast("Generate and save a SOAP note before creating ICD-10/CPT codes.", "error");
    return;
  }
  showCodingWorkspace({ noteId, autoGenerate });
}

function showNotes(patient = null) {
  if (!canLeaveVisit()) return;
  if (patient) {
    if (!selectedPatient || selectedPatient._id !== patient._id) {
      assistantMessages = [];
      assistantBusy = false;
    }
    notesFilterPatientId = patient._id || "";
    selectedPatient = patient;
    renderSelectedPatient();
    renderPatientList();
  } else {
    notesFilterPatientId = "";
  }
  setView("notes");
  document.getElementById("eyebrowText").textContent = notesFilterPatientId ? "Patient notes" : "Notes archive";
  fetchNotes(notesFilterPatientId);
}

function showPatientAssistant(patient = null) {
  if (!canLeaveVisit()) return;
  if (patient) {
    if (!selectedPatient || selectedPatient._id !== patient._id) {
      assistantMessages = [];
      assistantBusy = false;
    }
    selectedPatient = patient;
    renderSelectedPatient();
    renderPatientList();
  }
  setView("assistant");
  document.getElementById("eyebrowText").textContent = selectedPatient
    ? `Patient Assistant: ${selectedPatient.name || "Unknown"}`
    : "Patient Assistant";
  renderPatientAssistant();
}

function showNotesForSelectedPatient() {
  if (!selectedPatient) {
    showToast("Select a patient first.", "error");
    return;
  }
  showNotes(selectedPatient);
}

let wsReconnectTimer = null;
let wsShouldReconnect = true;

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  wsShouldReconnect = true;
  try {
    ws = new WebSocket(WS_URL);
  } catch (error) {
    console.warn("[WS] Unable to open socket", error);
    scheduleWebSocketReconnect();
    return;
  }
  ws.onopen = () => console.log("[WS] Connected");
  ws.onerror = () => {
    // Browser also emits close; avoid noisy error spam from extensions / BFCache.
  };
  ws.onclose = (event) => {
    if (event.code === 4401) {
      location.replace("/consultation/login");
      return;
    }
    if (wsShouldReconnect && document.visibilityState !== "hidden") {
      scheduleWebSocketReconnect();
    }
  };
  ws.onmessage = handleServerMessage;
}

function scheduleWebSocketReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    if (wsShouldReconnect) connectWebSocket();
  }, 1500);
}

function closeWebSocketForCache() {
  wsShouldReconnect = false;
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  if (ws && ws.readyState < WebSocket.CLOSING) {
    try { ws.close(); } catch (_) { /* ignore */ }
  }
}

window.addEventListener("pagehide", closeWebSocketForCache);
window.addEventListener("pageshow", (event) => {
  wsShouldReconnect = true;
  if (event.persisted || !ws || ws.readyState !== WebSocket.OPEN) {
    connectWebSocket();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    wsShouldReconnect = true;
    if (!ws || ws.readyState !== WebSocket.OPEN) connectWebSocket();
  }
});

function handleServerMessage(event) {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case "recording_started":
      pendingRecordingStart = false;
      isRecording = true;
      if (activeWorkflow) activeWorkflow.state = "CONSULTATION_ACTIVE";
      durationSec = 0;
      setRecordingUI(true);
      startDurationTimer();
      updateRecordingBanner("Recording live", "Audio is streaming to the server. Stop the recording when the consultation is complete.");
      setWorkspaceStatus("Recording live");
      renderClinicFlow();
      break;

    case "transcript_complete":
      if (Array.isArray(msg.urdu_conversation)) {
        diarizedTranscript = msg.urdu_conversation;
        transcriptMode = "urdu";
        renderTranscript();
      }
      updateRecordingBanner("Urdu transcript ready", "The raw Urdu transcription is ready. English translation is being prepared next.");
      break;

    case "translation_complete":
      if (Array.isArray(msg.english_conversation)) {
        fullTranscript = msg.english_conversation;
        renderTranscript();
        updateRecordingBanner("English transcript ready", "The transcript panel keeps the Urdu transcript available and now also includes the English view for note review.");
      }
      break;

    case "processing":
      showProcessingInSoap(msg.message);
      break;

    case "soap_note":
      stopDurationTimer();
      isRecording = false;
      setRecordingUI(false);
      generatedSoap = normalizeSoapDraft(msg.soap || null);
      generatedNoteState = msg.note_state || generatedSoap.state || "AI_DRAFT";
      if (activeWorkflow) activeWorkflow.state = "NOTE_REVIEW_REQUIRED";
      soapDraftTouched = false;
      soapSaveBusy = false;
      soapLastSavedNoteId = msg.note_id || "";
      soapSectionEditing = {};
      soapSectionSnapshots = {};
      if (Array.isArray(msg.urdu_transcript) && msg.urdu_transcript.length) {
        diarizedTranscript = msg.urdu_transcript;
      }
      if (Array.isArray(msg.english_transcript) && msg.english_transcript.length) {
        fullTranscript = msg.english_transcript;
      }
      renderTranscript();
      renderSoapNote(generatedSoap, fullTranscript);
      updateRecordingBanner("SOAP draft ready", "Review the note, edit any section you want, then save it to the Notes page.");
      setWorkspaceStatus("Draft ready");
      renderPatientAssistant();
      renderClinicFlow();
      showToast("Draft saved. Review the SOAP sections before approval.");
      break;

    case "error":
      stopDurationTimer();
      isRecording = false;
      pendingRecordingStart = false;
      releaseMicrophone();
      setRecordingUI(false);
      setWorkspaceStatus("Attention needed");
      showToast(msg.message || "Processing failed.", "error");
      break;

    case "pong":
      break;
  }
}

async function fetchPatients() {
  try {
    const response = await fetch("/api/patients");
    if (!response.ok) throw new Error("Unable to load patient records.");
    allPatients = await response.json();
    filteredPatients = [...allPatients];
    updatePatientStats();
    renderPatientList();
  } catch (error) {
    console.error("Failed to fetch patients", error);
    showToast("Unable to load patient records.", "error");
  }
}

async function fetchDoctorQueue({ quiet = false } = {}) {
  try {
    const response = await fetch("/api/appointments/doctor-queue");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load appointments."));
    doctorAppointments = Array.isArray(payload.appointments) ? payload.appointments : [];
    doctorScheduleZone = payload.timezone || "Asia/Karachi";
    renderDoctorAppointmentList();
  } catch (error) {
    console.error("Failed to fetch doctor appointment queue", error);
    if (!quiet) showToast("Unable to load the appointment queue.", "error");
  }
}

async function refreshDashboardQueues() {
  await Promise.all([
    fetchPatients(),
    fetchDoctorQueue({ quiet: true }),
  ]);
}

function renderDoctorAppointmentList() {
  const container = document.getElementById("doctorAppointmentList");
  const badge = document.getElementById("appointmentCountBadge");
  if (!container || !badge) return;
  const pending = doctorAppointments.filter(x => x.status === "REQUESTED");
  const scheduled = doctorAppointments.filter(x => x.status !== "REQUESTED");
  const pendingList = document.getElementById("pendingRequestList");
  document.getElementById("pendingRequestCount").textContent = `${pending.length} pending`;
  const count = scheduled.length;
  badge.textContent = `${count} booked`;
  if (!doctorAppointments.length) {
    if(pendingList) pendingList.innerHTML = '<div class="appointment-empty">No pending requests for this doctor.</div>';
    container.innerHTML = `
      <div class="appointment-empty">
        No confirmed appointments are assigned to your schedule yet.
      </div>`;
    return;
  }
  const renderRow = (appointment) => {
    const date = new Date(appointment.start_at);
    const dateLabel = appointmentDateLabel(date);
    const timeLabel = Number.isNaN(date.getTime())
      ? "Time pending"
      : date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    const details = [appointment.department, appointment.visit_type]
      .filter(Boolean)
      .map((value) => escHtml(value))
      .join(" &middot; ");
    const statusLabel = String(appointment.status || "")
      .replaceAll("_", " ")
      .toLowerCase();
    return `
      <button
        class="appointment-row"
        type="button"
        onclick="openScheduledPatient('${escAttr(appointment.patient_id || "")}')"
      >
        <span class="appointment-time">
          <strong>${escHtml(dateLabel)}</strong>
          <span>${escHtml(timeLabel)}</span>
        </span>
        <span class="appointment-copy">
          <strong>${escHtml(appointment.patient_name || "Unknown patient")}</strong>
          <span>${escHtml(appointment.current_complaint || "No complaint recorded")}</span>
          <span>${details}</span>
        </span>
        <span class="appointment-status">${escHtml(statusLabel)}</span>
      </button>`;
  };
  if(pendingList) pendingList.innerHTML = pending.map(renderRow).join("") || '<div class="appointment-empty">No pending requests for this doctor.</div>';
  container.innerHTML = scheduled.map(renderRow).join("") || '<div class="appointment-empty">No confirmed appointments are assigned to your schedule yet.</div>';
  if(window.lucide)lucide.createIcons();
}

function appointmentDateLabel(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "Date pending";
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  const key = (value) => [
    value.getFullYear(),
    value.getMonth(),
    value.getDate(),
  ].join("-");
  if (key(date) === key(today)) return "Today";
  if (key(date) === key(tomorrow)) return "Tomorrow";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

async function openScheduledPatient(patientId) {
  if (!allPatients.some((patient) => patient._id === patientId)) {
    await fetchPatients();
  }
  openPatientVisitById(patientId);
}

let notesRequestRevision = 0;
async function fetchNotes() {
  const requestRevision = ++notesRequestRevision;
  try {
    const response = await fetch("/api/notes");
    if (!response.ok) throw new Error("Unable to load saved notes.");
    const notesPayload = await response.json();
    if (requestRevision !== notesRequestRevision) return;
    savedNotes = notesPayload;
    updateNoteStats();
    renderNotesPage();
    renderPatientAssistant();
  } catch (error) {
    console.error("Failed to fetch notes", error);
    showToast("Unable to load saved notes.", "error");
  }
}

function updatePatientStats() {
  const count = allPatients.length;
  document.getElementById("statPatients").textContent = String(count).padStart(2, "0");
  document.getElementById("patientCountBadge").textContent = `${count} patient${count === 1 ? "" : "s"}`;
}

function updateNoteStats() {
  renderRecentDrafts();
  const count = savedNotes.length;
  document.getElementById("statNotes").textContent = String(count).padStart(2, "0");
  document.getElementById("sidebarNoteCount").textContent = String(count).padStart(2, "0");
}

function filterPatients(query) {
  const q = String(query || "").trim().toLowerCase();
  filteredPatients = !q ? [...allPatients] : allPatients.filter((patient) => {
    const name = (patient.name || "").toLowerCase();
    const complaint = (patient.current_complaint || "").toLowerCase();
    const history = (patient.past_medical_history || "").toLowerCase();
    return name.includes(q) || complaint.includes(q) || history.includes(q);
  });
  renderPatientList();
}

function renderPatientList() {
  const container = document.getElementById("dashboardPatientList");
  if (!filteredPatients.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div>
          <h4>No patient records found</h4>
          <p>Try a different search term or add a new intake record before starting the workflow.</p>
        </div>
      </div>`;
    return;
  }

  container.innerHTML = filteredPatients.map((patient) => {
    const active = selectedPatient && selectedPatient._id === patient._id;
    return `
      <button class="patient-row ${active ? "active" : ""}" onclick="openPatientVisitById('${escAttr(patient._id || "")}')">
        <div class="avatar">${getInitials(patient.name || "Unknown")}</div>
        <div class="row-copy">
          <strong>${escHtml(patient.name || "Unknown")}</strong>
          <span>${escHtml(buildPatientSubtitle(patient))}</span>
        </div>
        <div class="row-meta">
          <span class="meta-badge">${escHtml(patient.age || "Age n/a")}</span>
          <span>${formatIntakeStamp(patient.recorded_at)}</span>
        </div>
      </button>`;
  }).join("");
}

function buildPatientSubtitle(patient) {
  const complaint = patient.current_complaint || "No chief complaint recorded";
  const history = patient.past_medical_history || "History not provided";
  return `${complaint}. ${history}`;
}

function formatIntakeStamp(value) {
  if (!value) return "Intake pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Intake recorded";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function openPatientVisitById(patientId) {
  const patient = allPatients.find((item) => item._id === patientId);
  if (!patient) {
    showToast("Patient record not found.", "error");
    return;
  }
  openPatientVisit(patient);
}

async function openPatientVisit(patient) {
  selectedPatient = patient;
  activeWorkflow = null;
  activeEncounter = null;
  activeAppointment = null;
  activeChallengeId = "";
  consentDecisions = null;
  developmentQuickStartEnabled = false;
  developmentQuickStartBusy = false;
  previsitSummary = null;
  previsitBusy = false;
  highlightedEvidenceIds = [];
  resetSoapDraftState();
  assistantMessages = [];
  assistantBusy = false;
  resetTranscriptState();
  renderTranscript();
  renderSoapEmptyState();
  renderPatientList();
  renderSelectedPatient();
  renderPrevisitSummary();
  showVisitWorkspace();
  await preparePatientWorkflow(patient);
}

function renderSelectedPatient() {
  const correctionButton = document.getElementById("correctIntakeBtn");
  if (correctionButton) correctionButton.disabled = !selectedPatient || Boolean(activeEncounter) || isRecording;
  const nameEl = document.getElementById("visitPatientName");
  const summaryEl = document.getElementById("visitPatientSummary");
  const avatarEl = document.getElementById("visitPatientAvatar");
  const chipsEl = document.getElementById("visitPatientChips");
  const intakeGrid = document.getElementById("intakeGrid");

  if (!selectedPatient) {
    nameEl.textContent = "No patient selected";
    summaryEl.textContent = "Choose a patient from Visits to load the intake summary, then start the consultation recording.";
    avatarEl.textContent = "MF";
    chipsEl.innerHTML = `<div class="ghost-chip">Waiting for patient</div>`;
    intakeGrid.innerHTML = `<div class="intake-item full"><small>Patient</small><strong>Select a patient to load intake details.</strong></div>`;
    updateRecordingBanner("Session status", "Waiting for a patient selection. The transcript panel will show the Urdu transcript first and the English translation after that.");
    renderClinicFlow();
    renderPatientAssistant();
    renderPrevisitSummary();
    return;
  }

  const patient = selectedPatient;
  const bookingSlot = activeAppointment?.start_at || patient.booking_slot_time || patient.booking_time_slot || "";
  const bookingDisplay = bookingSlot ? formatDateTime(bookingSlot) : "";
  nameEl.textContent = patient.name || "Unknown";
  summaryEl.textContent = patient.current_complaint || "No chief complaint recorded.";
  avatarEl.textContent = getInitials(patient.name || "Unknown");
  chipsEl.innerHTML = `
    <div class="ghost-chip" title="Age">${studioIcon('user-round')}${escHtml(patient.age || "Not recorded")}</div>
    <div class="ghost-chip" title="Phone">${studioIcon('phone')}${escHtml(patient.phone_number || "Not recorded")}</div>
    <div class="ghost-chip" title="First visit">${studioIcon('badge-check')}${escHtml(patient.first_visit || "Unknown")}</div>
    <div class="ghost-chip" title="Appointment">${studioIcon('calendar-clock')}${escHtml(bookingDisplay || "No appointment")}</div>`;

  const fields = [
    ["Patient Name", patient.name || "Unknown"],
    ["Age", patient.age || "Not documented"],
    ["Phone", patient.phone_number || "Not documented"],
    ["First Visit", patient.first_visit || "Not documented"],
    ...(patient.blood_pressure ? [["Blood Pressure", patient.blood_pressure]] : []),
    ["Booking Slot", bookingDisplay || "Not documented"],
    ["Past Medical History", patient.past_medical_history || "Not documented"],
    ["Chief Complaint", patient.current_complaint || "Not documented", true],
  ];

  intakeGrid.innerHTML = fields.map(([label, value, full]) => `
    <div class="intake-item ${full ? "full" : ""}">
      <small>${escHtml(label)}</small>
      <strong>${escHtml(value)}</strong>
    </div>`).join("");

  updateRecordingBanner("Patient record loaded", "Follow the visit stages to prepare, capture, review, and finish the encounter.");
  renderClinicFlow();
  renderPatientAssistant();
  renderPrevisitSummary();
}

async function openIntakeCorrection() {
  if (!selectedPatient || activeEncounter || isRecording) return;
  const patientId = selectedPatient._id;
  try {
    const response = await fetch("/api/patients/" + encodeURIComponent(patientId));
    const payload = await response.json();
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load the current intake."));
    if (selectedPatient?._id !== patientId) return;
    intakeCorrectionSnapshot = payload;
    document.getElementById("intakeCorrectionError").textContent = "";
    selectIntakeCorrectionField();
    document.getElementById("intakeCorrectionDialog").showModal();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function selectIntakeCorrectionField() {
  const field = document.getElementById("intakeCorrectionField").value;
  const sourceField = field === "age_text" ? "age" : field;
  document.getElementById("intakeCorrectionValue").value = intakeCorrectionSnapshot?.[sourceField] || "";
  document.getElementById("intakeCorrectionConfirmed").checked = false;
}

async function saveIntakeCorrection(event) {
  event.preventDefault();
  const snapshot = intakeCorrectionSnapshot;
  const button = document.getElementById("saveIntakeCorrectionBtn");
  if (!snapshot || button.disabled || !document.getElementById("intakeCorrectionConfirmed").checked) return;
  const field = document.getElementById("intakeCorrectionField").value;
  const value = document.getElementById("intakeCorrectionValue").value.trim();
  const errorElement = document.getElementById("intakeCorrectionError");
  button.disabled = true;
  errorElement.textContent = "";
  try {
    const response = await fetch("/api/patients/" + encodeURIComponent(snapshot.patient_id) + "/intake", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_updated_at: snapshot.updated_at,
        changes: { [field]: value },
        confirmed: true,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to save this correction."));
    allPatients = allPatients.map(patient => patient._id === snapshot.patient_id ? { ...patient, ...payload } : patient);
    if (selectedPatient?._id === snapshot.patient_id) {
      selectedPatient = { ...selectedPatient, ...payload };
      renderSelectedPatient();
    }
    renderPatientList();
    await fetchDoctorQueue();
    closeWorkflowDialog("intakeCorrectionDialog");
    intakeCorrectionSnapshot = null;
    showToast("Patient intake corrected.");
  } catch (error) {
    errorElement.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function preparePatientWorkflow(patient) {
  try {
    const response = await fetch("/api/workflows/prepare-consultation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: patient._id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to prepare the consultation."));
    if (!selectedPatient || selectedPatient._id !== patient._id) return false;
    activeWorkflow = payload.workflow;
    activeAppointment = payload.appointment || null;
    activeEncounter = payload.encounter || null;
    activeChallengeId = "";
    developmentQuickStartEnabled = false;
    consentDecisions = Object.fromEntries(
      (payload.consents || []).map((item) => [item.consent_type, item]),
    );
    if (activeEncounter) {
      await Promise.all([refreshConsentDecisions(), refreshPrevisitSummary()]);
    }
    renderClinicFlow();
    return true;
  } catch (error) {
    showToast(error.message || "Unable to prepare the consultation.", "error");
    renderClinicFlow();
    return false;
  }
}

function isConsultationRecordable() {
  return ["CONSULTATION_READY", "CONSULTATION_ACTIVE"].includes(activeWorkflow?.state || "");
}

async function ensureConsultationReadyForRecording() {
  if (!selectedPatient) {
    showToast("Select a patient first.", "error");
    return false;
  }
  if (isConsultationRecordable() && activeEncounter) {
    return true;
  }
  const prepared = await preparePatientWorkflow(selectedPatient);
  return Boolean(prepared && isConsultationRecordable() && activeEncounter);
}

async function fetchClinicalTemplates() {
  try {
    const response = await fetch("/api/templates");
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load clinical templates."));
    clinicalTemplates = Array.isArray(payload.templates) ? payload.templates : [];
    if (!clinicalTemplates.some((item) => item.template_id === selectedTemplateId)) {
      selectedTemplateId = clinicalTemplates[0]?.template_id || "TPL-GP-01";
    }
  } catch (error) {
    console.error("Failed to fetch clinical templates", error);
  }
  renderClinicalTemplateOptions();
}

function renderClinicalTemplateOptions() {
  const select = document.getElementById("clinicalTemplateSelect");
  if (!select) return;
  const templates = clinicalTemplates.length
    ? clinicalTemplates
    : [{ template_id: "TPL-GP-01", name: "General Practice SOAP" }];
  select.innerHTML = templates
    .map((item) => `<option value="${escAttr(item.template_id)}">${escHtml(item.name)}</option>`)
    .join("");
  select.value = selectedTemplateId;
  select.disabled = isRecording || pendingRecordingStart;
}

function selectClinicalTemplate(templateId) {
  if (isRecording || pendingRecordingStart) return;
  if (clinicalTemplates.length && !clinicalTemplates.some((item) => item.template_id === templateId)) return;
  selectedTemplateId = templateId || "TPL-GP-01";
}

function renderClinicFlow() {
  const state = activeWorkflow?.state || "";
  const statePill = document.getElementById("workflowStatePill");
  if (!statePill) return;
  statePill.textContent = state ? state.replaceAll("_", " ") : selectedPatient ? "Preparing consultation" : "No patient selected";

  const consultationReady = isConsultationRecordable();
  const requiredConsentGranted = hasRequiredConsent();
  const consentStatus = document.getElementById("consentStatus");
  if (consentStatus) {
    if (!selectedPatient) {
      consentStatus.textContent = "Select a patient to prepare the consultation.";
    } else if (!activeEncounter || !consultationReady) {
      consentStatus.textContent = "Preparing a recordable visit. Consent will unlock next.";
    } else if (requiredConsentGranted) {
      consentStatus.textContent = `Required choices granted. Audio retention is ${consentDecisions?.AUDIO_RETENTION?.decision ? "enabled" : "off"}.`;
    } else {
      consentStatus.textContent = "Grant the required recording and AI choices before capture.";
    }
  }

  const openConsentBtn = document.getElementById("openConsentBtn");
  if (openConsentBtn) {
    openConsentBtn.disabled = !activeEncounter || !consultationReady || pendingRecordingStart || isRecording;
    openConsentBtn.textContent = requiredConsentGranted ? "Update choices" : "Record choices";
  }
  const regeneratePrevisitBtn = document.getElementById("regeneratePrevisitBtn");
  if (regeneratePrevisitBtn) regeneratePrevisitBtn.disabled = !activeEncounter || previsitBusy;
  // Keep the recording controls clickable whenever a patient is selected; startRecording
  // will prepare a fresh visit / prompt for consent as needed.
  const recordToggleBtn = document.getElementById("recordToggleBtn");
  if (recordToggleBtn) recordToggleBtn.disabled = !selectedPatient || pendingRecordingStart;
  const recBtn = document.getElementById("recBtn");
  if (recBtn) recBtn.disabled = !selectedPatient || pendingRecordingStart;
  const manualPathNotice = document.getElementById("manualPathNotice");
  if (manualPathNotice) manualPathNotice.hidden = !selectedPatient || requiredConsentGranted;
}

function hasRequiredConsent() {
  return ["AUDIO_RECORDING", "AI_TRANSCRIPTION", "AI_DOCUMENTATION"]
    .every((key) => consentDecisions?.[key]?.decision && !consentDecisions[key].revoked_at);
}

async function startDevelopmentQuickVisit() {
  if (
    !selectedPatient
    || !developmentQuickStartEnabled
    || developmentQuickStartBusy
    || isRecording
    || pendingRecordingStart
  ) return;
  developmentQuickStartBusy = true;
  renderClinicFlow();
  try {
    const response = await fetch("/api/workflows/development/quick-start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: selectedPatient._id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to prepare the test visit."));
    activeWorkflow = payload.workflow;
    activeAppointment = payload.appointment;
    activeEncounter = payload.encounter;
    activeChallengeId = "";
    consentDecisions = Object.fromEntries(
      (payload.consents || []).map((item) => [item.consent_type, item]),
    );
    previsitSummary = null;
    highlightedEvidenceIds = [];
    resetSoapDraftState();
    resetTranscriptState();
    renderTranscript();
    renderSoapEmptyState();
    await refreshPrevisitSummary();
    showVisitWorkspace();
    showToast("Synthetic test visit ready. Recording is enabled and audio retention is off.");
  } catch (error) {
    showToast(error.message || "Unable to prepare the test visit.", "error");
  } finally {
    developmentQuickStartBusy = false;
    renderClinicFlow();
  }
}

async function requestPatientOtp() {
  if (!selectedPatient || !activeWorkflow) return;
  try {
    const response = await fetch("/api/verification/challenges", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient_id: selectedPatient._id, workflow_id: activeWorkflow.workflow_id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to send the verification code."));
    activeChallengeId = payload.challenge_id;
    document.getElementById("otpDeliveryMessage").textContent = `A six-digit code was sent to the phone ending ${payload.phone_last_four}.`;
    document.getElementById("patientOtpInput").value = "";
    const banner = document.getElementById("developmentOtpBanner");
    banner.hidden = !payload.development_otp;
    document.getElementById("developmentOtpValue").textContent = payload.development_otp || "";
    document.getElementById("verificationDialog").showModal();
  } catch (error) {
    showToast(error.message || "Unable to send the verification code.", "error");
  }
}

async function resendPatientOtp() {
  if (!activeChallengeId) return;
  try {
    const response = await fetch(`/api/verification/challenges/${encodeURIComponent(activeChallengeId)}/resend`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to resend the code."));
    document.getElementById("patientOtpInput").value = "";
    const banner = document.getElementById("developmentOtpBanner");
    banner.hidden = !payload.development_otp;
    document.getElementById("developmentOtpValue").textContent = payload.development_otp || "";
    showToast("A new verification code was sent.");
  } catch (error) {
    showToast(error.message || "Unable to resend the code.", "error");
  }
}

async function verifyPatientOtp(event) {
  event.preventDefault();
  const code = document.getElementById("patientOtpInput").value.trim();
  if (!activeChallengeId || !/^\d{6}$/.test(code)) return;
  try {
    const response = await fetch(`/api/verification/challenges/${encodeURIComponent(activeChallengeId)}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Verification failed."));
    const intake = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflow.workflow_id)}/complete-intake`, { method: "POST" });
    const intakePayload = await intake.json().catch(() => ({}));
    if (!intake.ok) throw new Error(apiMessage(intakePayload, "Unable to complete the existing intake."));
    activeWorkflow = intakePayload.workflow;
    closeWorkflowDialog("verificationDialog");
    renderClinicFlow();
    showToast("Patient verified. Appointment booking is ready.");
  } catch (error) {
    showToast(error.message || "Verification failed.", "error");
  }
}

async function openBookingDialog() {
  if (!selectedPatient || activeWorkflow?.state !== "BOOKING_REQUIRED") return;
  try {
    if (!appointmentConfiguration) {
      const response = await fetch("/api/appointments/configuration");
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiMessage(payload, "Appointment configuration is unavailable."));
      appointmentConfiguration = payload;
    }
    document.getElementById("bookingDepartment").innerHTML = appointmentConfiguration.departments
      .map((item) => `<option value="${escAttr(item.department_id)}">${escHtml(item.name)}</option>`).join("");
    document.getElementById("bookingVisitType").innerHTML = appointmentConfiguration.visit_types
      .map((item) => `<option value="${escAttr(item.visit_type_id)}">${escHtml(item.name)}</option>`).join("");
    document.getElementById("bookingStartDate").value = localDateAfter(2);
    filterBookingDoctors();
    document.getElementById("bookingSlot").innerHTML = '<option value="">Find an available slot</option>';
    document.getElementById("bookingDialog").showModal();
  } catch (error) {
    showToast(error.message || "Appointment configuration is unavailable.", "error");
  }
}

function filterBookingDoctors() {
  if (!appointmentConfiguration) return;
  const departmentId = document.getElementById("bookingDepartment").value;
  const doctors = appointmentConfiguration.practitioners.filter((item) => item.department_id === departmentId);
  document.getElementById("bookingDoctor").innerHTML = doctors
    .map((item) => `<option value="${escAttr(item.practitioner_id)}">${escHtml(item.display_name)}</option>`).join("");
  syncBookingProfile();
}

function syncBookingProfile() {
  document.getElementById("bookingSlot").innerHTML = '<option value="">Find an available slot</option>';
}

let availableSlotsRequestRevision = 0;
async function loadAvailableSlots() {
  const requestRevision = ++availableSlotsRequestRevision;
  const practitionerId = document.getElementById("bookingDoctor").value;
  const visitTypeId = document.getElementById("bookingVisitType").value;
  const startDate = document.getElementById("bookingStartDate").value;
  if (!selectedPatient || !practitionerId || !visitTypeId || !startDate) return;
  const patientId = selectedPatient._id;
  document.getElementById("bookingSlot").innerHTML = '<option value="">Checking available times…</option>';
  const params = new URLSearchParams({
    patient_id: patientId,
    practitioner_id: practitionerId,
    visit_type_id: visitTypeId,
    start_date: startDate,
    days: "7",
  });
  try {
    const response = await fetch(`/api/appointments/availability?${params}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load appointment slots."));
    if (requestRevision !== availableSlotsRequestRevision || selectedPatient?._id !== patientId || document.getElementById("bookingDoctor").value !== practitionerId || document.getElementById("bookingVisitType").value !== visitTypeId || document.getElementById("bookingStartDate").value !== startDate) return;
    document.getElementById("bookingSlot").innerHTML = payload.slots.length
      ? '<option value="">Select a time</option>' + payload.slots.map((slot) => `<option value="${escAttr(slot.start_at)}">${escHtml(formatDateTime(slot.start_at))}</option>`).join("")
      : '<option value="">No slots available</option>';
  } catch (error) {
    showToast(error.message || "Unable to load appointment slots.", "error");
  }
}

async function bookSelectedAppointment(event) {
  event.preventDefault();
  const practitionerId = document.getElementById("bookingDoctor").value;
  const profile = appointmentConfiguration?.practitioners.find((item) => item.practitioner_id === practitionerId);
  const startAt = document.getElementById("bookingSlot").value;
  if (!selectedPatient || !profile || !startAt || !activeWorkflow) return;
  try {
    const response = await fetch("/api/appointments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: selectedPatient._id,
        practitioner_id: practitionerId,
        department_id: profile.department_id,
        location_id: profile.location_id,
        visit_type_id: document.getElementById("bookingVisitType").value,
        start_at: startAt,
        idempotency_key: `web-${crypto.randomUUID()}`,
        workflow_id: activeWorkflow.workflow_id,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to book the appointment."));
    activeAppointment = payload.appointment;
    activeWorkflow = payload.workflow;
    closeWorkflowDialog("bookingDialog");
    renderClinicFlow();
    showToast("Appointment confirmed.");
  } catch (error) {
    showToast(error.message || "Unable to book the appointment.", "error");
  }
}

async function checkInPatient() {
  if (!activeWorkflow) return;
  try {
    const response = await fetch(`/api/workflows/${encodeURIComponent(activeWorkflow.workflow_id)}/check-in`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to check in the patient."));
    activeWorkflow = payload.workflow;
    activeAppointment = payload.appointment;
    activeEncounter = payload.encounter;
    consentDecisions = null;
    renderClinicFlow();
    await refreshPrevisitSummary();
    openConsentDialog();
  } catch (error) {
    showToast(error.message || "Unable to check in the patient.", "error");
  }
}

function openConsentDialog() {
  if (!activeEncounter) return;
  document.getElementById("consentRecording").checked = Boolean(consentDecisions?.AUDIO_RECORDING?.decision);
  document.getElementById("consentTranscription").checked = Boolean(consentDecisions?.AI_TRANSCRIPTION?.decision);
  document.getElementById("consentDocumentation").checked = Boolean(consentDecisions?.AI_DOCUMENTATION?.decision);
  document.getElementById("consentRetention").checked = Boolean(consentDecisions?.AUDIO_RETENTION?.decision);
  document.getElementById("consentDialog").showModal();
}

async function saveConsentChoices(event) {
  event.preventDefault();
  if (!activeEncounter) return;
  try {
    const response = await fetch("/api/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        encounter_id: activeEncounter.encounter_id,
        audio_recording: document.getElementById("consentRecording").checked,
        ai_transcription: document.getElementById("consentTranscription").checked,
        ai_documentation: document.getElementById("consentDocumentation").checked,
        audio_retention: document.getElementById("consentRetention").checked,
        consent_text_version: "CONSENT-V1",
        capture_method: "DOCTOR_ATTESTATION",
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to save consent choices."));
    consentDecisions = Object.fromEntries(payload.consents.map((item) => [item.consent_type, item]));
    closeWorkflowDialog("consentDialog");
    renderClinicFlow();
    showToast(hasRequiredConsent() ? "Required consent recorded. Recording is ready." : "Choices saved. Recording stays off without the required permissions.");
  } catch (error) {
    showToast(error.message || "Unable to save consent choices.", "error");
  }
}

async function refreshConsentDecisions() {
  if (!activeEncounter) return;
  const revision = contextRevision;
  const response = await fetch(`/api/consents/encounters/${encodeURIComponent(activeEncounter.encounter_id)}`);
  if (response.ok) {const payload=await response.json(); if (revision===contextRevision) consentDecisions=payload;}
}

async function refreshPrevisitSummary() {
  const revision = contextRevision;
  if (!selectedPatient || !activeEncounter) {
    previsitSummary = null;
    renderPrevisitSummary();
    return;
  }
  try {
    const response = await fetch(`/api/patients/${encodeURIComponent(selectedPatient._id)}/previsit-summaries/latest`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load the pre-visit brief."));
    if (revision !== contextRevision) return;
    previsitSummary = payload?.exists === false || payload?.summary === null ? null : payload;
  } catch (error) {
    console.warn("Pre-visit brief unavailable yet", error?.message || error);
    previsitSummary = null;
  }
  renderPrevisitSummary();
}

async function generatePrevisitSummary() {
  if (!selectedPatient || !activeEncounter || previsitBusy) return;
  previsitBusy = true;
  renderPrevisitSummary();
  renderClinicFlow();
  try {
    const response = await fetch(`/api/patients/${encodeURIComponent(selectedPatient._id)}/previsit-summaries`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ encounter_id: activeEncounter.encounter_id }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to generate the pre-visit brief."));
    previsitSummary = payload;
    showToast("Pre-visit brief generated from approved records.");
  } catch (error) {
    showToast(error.message || "Unable to generate the pre-visit brief.", "error");
  } finally {
    previsitBusy = false;
    renderPrevisitSummary();
    renderClinicFlow();
  }
}

function renderPrevisitSummary() {
  const content = document.getElementById("previsitContent");
  const button = document.getElementById("regeneratePrevisitBtn");
  if (!content || !button) return;
  button.textContent = previsitBusy ? "Preparing..." : previsitSummary ? "Regenerate" : "Generate brief";
  button.disabled = !activeEncounter || previsitBusy;
  if (previsitBusy) {
    content.innerHTML = "<p>Preparing a patient-scoped brief from intake and approved records.</p>";
    return;
  }
  if (!selectedPatient || !activeEncounter) {
    content.innerHTML = "<p>Select and check in a patient to prepare a stored pre-visit brief.</p>";
    return;
  }
  if (!previsitSummary) {
    content.innerHTML = "<p>No stored brief exists for this patient. Generate it explicitly when the doctor is ready.</p>";
    return;
  }
  const sections = Array.isArray(previsitSummary.sections) ? previsitSummary.sections : [];
  const warnings = Array.isArray(previsitSummary.warnings) ? previsitSummary.warnings : [];
  content.innerHTML = [
    ...sections.map((section) => `
      <section class="previsit-section">
        <h4>${escHtml(section.title || "Clinical context")}</h4>
        <ul>${(section.items || []).map((item) => `<li>${escHtml(item.text || "")}</li>`).join("")}</ul>
      </section>`),
    ...warnings.map((warning) => `<div class="clinical-warning">${escHtml(warning)}</div>`),
  ].join("") || "<p>No approved clinical context is available yet.</p>";
}

function closeWorkflowDialog(dialogId) {
  const dialog = document.getElementById(dialogId);
  if (dialog?.open) dialog.close();
}

function localDateAfter(days) {
  const value = new Date();
  value.setDate(value.getDate() + days);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isLocalMicHost() {
  return ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
}

function getMicrophoneAccessMessage(error) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return "This browser does not support microphone capture. Use a recent version of Chrome, Edge, or Firefox.";
  }

  if (!window.isSecureContext && !isLocalMicHost()) {
    return "Microphone access requires HTTPS or localhost. Open Medflow AI from localhost or over HTTPS and try again.";
  }

  switch (error?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone access is blocked. Allow the microphone for this site in the browser address bar, then try again.";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "No microphone was detected. Connect a microphone and try again.";
    case "NotReadableError":
    case "TrackStartError":
      return "The microphone is busy in another application. Close the other app and try again.";
    default:
      return "Unable to start microphone capture. Check the browser microphone permission and try again.";
  }
}

function showMicrophoneAccessError(error) {
  const message = getMicrophoneAccessMessage(error);
  updateRecordingBanner("Microphone access needed", message);
  setWorkspaceStatus("Microphone blocked");
  showToast(message, "error");
}

async function startRecordingFromDashboard() {
  if (!selectedPatient && allPatients.length) {
    renderPatientAssistant();
    await openPatientVisit(allPatients[0]);
  } else if (!selectedPatient) {
    showToast("No patients available. Add an intake record first.", "error");
    return;
  } else if (!isConsultationRecordable() || !activeEncounter) {
    await preparePatientWorkflow(selectedPatient);
  }

  showVisitWorkspace();
  await startRecording();
}

async function toggleRecording() {
  if (pendingRecordingStart) return;
  if (isRecording) {
    stopRecording();
  } else {
    await startRecording();
  }
}

async function startRecording() {
  if (!selectedPatient) {
    showToast("Select a patient first.", "error");
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showMicrophoneAccessError();
    return;
  }

  if (!window.isSecureContext && !isLocalMicHost()) {
    showMicrophoneAccessError();
    return;
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast("Connecting to the server. Try again in a moment.", "error");
    connectWebSocket();
    return;
  }

  const ready = await ensureConsultationReadyForRecording();
  if (!ready) {
    showToast("Unable to prepare a recordable consultation for this patient.", "error");
    renderClinicFlow();
    return;
  }

  if (!hasRequiredConsent()) {
    showToast("Grant Recording and AI consent before starting the capture.", "error");
    renderClinicFlow();
    openConsentDialog();
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        noiseSuppression: false,
        echoCancellation: false,
        autoGainControl: false,
      },
      video: false,
    });
  } catch (error) {
    showMicrophoneAccessError(error);
    return;
  }

  resetSoapDraftState();
  resetTranscriptState();
  renderTranscript();
  renderSoapEmptyState();

  audioContext = new AudioContext();
  captureSampleRate = audioContext.sampleRate || 16000;
  const source = audioContext.createMediaStreamSource(mediaStream);
  scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  captureSink = audioContext.createGain();
  captureSink.gain.value = 0;

  source.connect(scriptProcessor);
  scriptProcessor.connect(captureSink);
  captureSink.connect(audioContext.destination);

  scriptProcessor.onaudioprocess = (event) => {
    if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;
    const float32 = event.inputBuffer.getChannelData(0);
    window.MedFlowMeter?.feed("consult", float32);
    const int16 = new Int16Array(float32.length);
    for (let index = 0; index < float32.length; index++) {
      int16[index] = Math.max(-32768, Math.min(32767, float32[index] * 32768));
    }
    ws.send(int16.buffer);
  };

  captureContext = { patientId: selectedPatient._id, workflowId: activeWorkflow.workflow_id, encounterId: activeEncounter.encounter_id, captureId: crypto.randomUUID() };
  ws.send(JSON.stringify({
    capture_id: captureContext.captureId,
    type: "start",
    patient_id: selectedPatient._id || "",
    workflow_id: activeWorkflow.workflow_id,
    encounter_id: activeEncounter.encounter_id,
    sample_rate: captureSampleRate,
    auto_soap: Boolean(window.medflowAutomaticSoap),
    template_id: selectedTemplateId,
  }));
  pendingRecordingStart = true;
  recordingStartTimer = setTimeout(() => {
    if (!pendingRecordingStart) return;
    pendingRecordingStart = false; captureContext = null; releaseMicrophone();
    if (ws) ws.close();
    showToast("Recording authorization timed out. Reconnect and try again.", "error");
    renderClinicFlow();
  }, 20000);
  document.getElementById("clinicalTemplateSelect").disabled = true;
  updateRecordingBanner("Authorizing recording", "The backend is checking the encounter, workflow, patient access, and consent records.");
  setWorkspaceStatus("Authorizing");
  showVisitWorkspace();
}

function stopRecording() {
  if (!isRecording) return;
  isRecording = false;

  releaseMicrophone();

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
  }

  stopDurationTimer();
  setRecordingUI(false);
  showProcessingInSoap("Processing recording, diarizing speakers, translating to English, and drafting the SOAP note for review...");
  updateRecordingBanner("Processing recording", "Medflow AI is transcribing the consultation, identifying speakers, translating the conversation, and preparing an editable SOAP draft.");
  setWorkspaceStatus("Processing");
}

function releaseMicrophone() {
  window.MedFlowMeter?.reset("consult");
  if (scriptProcessor) {
    scriptProcessor.disconnect();
    scriptProcessor = null;
  }
  if (captureSink) {
    captureSink.disconnect();
    captureSink = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
}

function setRecordingUI(recording) {
  const recBtn = document.getElementById("recBtn");
  const recCore = document.getElementById("recCore");
  const recTitle = document.getElementById("recTitle");
  const recCopy = document.getElementById("recCopy");
  const waveBars = document.getElementById("waveBars");
  const toggleBtn = document.getElementById("recordToggleBtn");

  recBtn.classList.toggle("recording", recording);
  recCore.classList.toggle("stop", recording);
  waveBars.style.display = recording ? "flex" : "none";
  recTitle.textContent = recording ? "Recording consultation" : "Ready to record";
  recCopy.textContent = recording ? "Stop when the consultation is complete." : "Transcript appears after processing.";
  toggleBtn.textContent = recording ? "Stop recording" : "Start recording";
  const templateSelect = document.getElementById("clinicalTemplateSelect");
  if (templateSelect) templateSelect.disabled = recording || pendingRecordingStart;
}

function startDurationTimer() {
  document.getElementById("recordingDuration").textContent = "00:00";
  durationInterval = setInterval(() => {
    durationSec += 1;
    const minutes = String(Math.floor(durationSec / 60)).padStart(2, "0");
    const seconds = String(durationSec % 60).padStart(2, "0");
    document.getElementById("recordingDuration").textContent = `${minutes}:${seconds}`;
  }, 1000);
}

function stopDurationTimer() {
  if (durationInterval) {
    clearInterval(durationInterval);
    durationInterval = null;
  }
}

function updateRecordingBanner(title, text) {
  document.getElementById("recordingStatusBanner").innerHTML = `<strong>${escHtml(title)}</strong>${escHtml(text)}`;
}

function setWorkspaceStatus(text) {
  document.getElementById("recordingStatePill").textContent = text;
}

function resetTranscriptState() {
  diarizedTranscript = [];
  fullTranscript = [];
  transcriptMode = "urdu";
  highlightedEvidenceIds = [];
}

function resetSoapDraftState() {
  generatedSoap = null;
  soapDraftTouched = false;
  soapSaveBusy = false;
  soapLastSavedNoteId = "";
  soapSectionEditing = {};
  soapSectionSnapshots = {};
}

function normalizeSoapDraft(soap) {
  const source = soap && typeof soap === "object" ? soap : {};
  return {
    ...source,
    patient_name: source.patient_name || selectedPatient?.name || "Unknown patient",
    generated_by: source.generated_by || "Medflow AI",
    visit_date: source.visit_date || new Date().toISOString(),
    subjective: typeof source.subjective === "string" ? source.subjective : "",
    objective: typeof source.objective === "string" ? source.objective : "",
    assessment: typeof source.assessment === "string" ? source.assessment : "",
    plan: typeof source.plan === "string" ? source.plan : "",
  };
}

function setTranscriptMode(mode) {
  if (mode === "english" && !fullTranscript.length) {
    return;
  }
  if (mode === "urdu" && !diarizedTranscript.length) {
    return;
  }
  transcriptMode = mode;
  renderTranscript();
}

function updateTranscriptHeader() {
  const heading = document.getElementById("transcriptHeading");
  const subtitle = document.getElementById("transcriptSubtitle");
  const urduBtn = document.getElementById("urduTranscriptBtn");
  const englishBtn = document.getElementById("englishTranscriptBtn");

  const viewingEnglish = transcriptMode === "english" && fullTranscript.length;

  heading.textContent = viewingEnglish ? "English translation" : "Urdu transcript";
  subtitle.textContent = viewingEnglish
    ? "Use this translated view for note review while keeping the raw transcript available for reference."
    : "Review the raw Urdu transcription before translation.";

  urduBtn.classList.toggle("active", !viewingEnglish);
  englishBtn.classList.toggle("active", viewingEnglish);
  urduBtn.disabled = !diarizedTranscript.length;
  englishBtn.disabled = !fullTranscript.length;
}

function generateNote() {
  if (isRecording) {
    stopRecording();
    return;
  }

  if (generatedSoap) {
    if (soapLastSavedNoteId) {
      selectedNoteId = soapLastSavedNoteId;
      showNotes(selectedPatient || null);
      return;
    }
    showToast("The SOAP draft is ready. Review the sections and save the note before opening it from the archive.", "error");
    return;
  }

  if (!selectedPatient) {
    showToast("Select a patient first.", "error");
    return;
  }

  showToast("Record and stop the consultation to generate a note.", "error");
}

// The relation of the visit's only attendant (e.g. "Mother"), so a doctor
// instruction addressed to the attendant can read "DOCTOR → MOTHER".
function singleAttendantRelation(entries) {
  const relations = new Set(
    (entries || []).filter((entry) => entry.speaker === "Attendant" && entry.speaker_relation)
      .map((entry) => entry.speaker_relation)
  );
  return relations.size === 1 ? [...relations][0] : "";
}

// An attendant is shown by relation ("Mother"); other speakers by role.
function speakerDisplayLabel(entry, attendantName = "") {
  const role = String(entry.speaker || "Transcript");
  let label = role === "Attendant" && entry.speaker_relation ? entry.speaker_relation : role;
  if (entry.addressed_to) {
    label += ` → ${entry.addressed_to === "Attendant" && attendantName ? attendantName : entry.addressed_to}`;
  }
  return label;
}

function renderTranscript() {
  const body = document.getElementById("transcriptBody");
  const entries = transcriptMode === "english" && fullTranscript.length ? fullTranscript : diarizedTranscript;
  updateTranscriptHeader();

  if (!entries || !entries.length) {
    body.innerHTML = `
      <div class="empty-state">
        <div>
          <h4>${transcriptMode === "english" ? "No English transcript yet" : "No diarized transcript yet"}</h4>
          <p>${transcriptMode === "english"
            ? "After translation finishes, the English doctor-patient conversation will appear here."
            : "After recording stops, the raw Urdu transcription will appear here before translation."}</p>
        </div>
      </div>`;
    return;
  }

  const attendantName = singleAttendantRelation(entries);
  body.innerHTML = entries.map((entry) => {
    const role = String(entry.speaker || "Transcript");
    const speaker = ["Doctor", "Patient", "Nurse", "Attendant"].includes(role) ? role.toLowerCase() : "transcript";
    const speakerLabel = speakerDisplayLabel(entry, attendantName);
    const utteranceId = String(entry.utterance_id || "");
    const highlighted = utteranceId && highlightedEvidenceIds.includes(utteranceId);
    return `
      <div class="transcript-entry ${highlighted ? "source-highlight" : ""}" data-utterance-id="${escAttr(utteranceId)}">
        <div class="speaker ${speaker}" title="${escAttr(role)}">${escHtml(speakerLabel).toUpperCase()}</div>
        <span class="turn-id">${escHtml(utteranceId)}${entry.needs_review ? " · Review role" : ""}</span><p dir="auto">${escHtml(entry.text || "")}</p>
      </div>`;
  }).join("");
}

function renderSoapEmptyState() {
  document.getElementById("soapContent").innerHTML = `
    <div class="soap-empty">
      <div>
        <h4>No SOAP note yet</h4>
        <p>Once the recording is processed, an editable SOAP draft will appear here. Review each section, make changes if needed, then save it to the Notes page.</p>
      </div>
    </div>`;
}

function showProcessingInSoap(message) {
  document.getElementById("soapContent").innerHTML = `
    <div class="processing-shell">
      <div>
        <div class="spinner"></div>
        <h4 style="font-size:22px;letter-spacing:-0.04em;">Preparing note</h4>
        <p style="margin-top:10px;color:var(--ink-2);line-height:1.7;">${escHtml(message || "Processing...")}</p>
      </div>
    </div>`;
}

function getSoapSaveLabel() {
  if (soapSaveBusy) return "Saving...";
  if (soapLastSavedNoteId && !soapDraftTouched) return "Saved";
  if (soapLastSavedNoteId && soapDraftTouched) return "Save updated note";
  if (soapDraftTouched) return "Save edited note";
  return "Save note";
}

function renderSoapSection(sectionKey, heading, value) {
  const editing = Boolean(soapSectionEditing[sectionKey]);
  const text = String(value || "");
  const claims = Array.isArray(generatedSoap?.structured_soap?.[sectionKey])
    ? generatedSoap.structured_soap[sectionKey]
    : [];
  const evidenceIds = [...new Set(claims.flatMap((claim) => claim.evidence_ids || []))];
  const sourceAction = evidenceIds.length
    ? `<button class="note-action" type="button" onclick="showSoapEvidence('${escAttr(sectionKey)}')">View source</button>`
    : "";

  return `
    <div class="soap-section ${editing ? "editing" : ""}" data-soap-section="${escAttr(sectionKey)}">
      <div class="soap-section-head">
        <h5>${escHtml(heading)}</h5>
        <div class="soap-inline-actions">
          ${sourceAction}
          ${editing
            ? `
              <button class="note-action" type="button" onclick="saveSoapSectionEdit('${escAttr(sectionKey)}')">Done</button>
              <button class="note-action" type="button" onclick="cancelSoapSectionEdit('${escAttr(sectionKey)}')">Cancel</button>`
            : `<button class="note-action" type="button" onclick="startSoapSectionEdit('${escAttr(sectionKey)}')">Edit section</button>`}
        </div>
      </div>
      ${editing
        ? `<textarea id="soapEditor_${escAttr(sectionKey)}" class="soap-editor-field" oninput="updateSoapSectionDraft('${escAttr(sectionKey)}', this.value)">${escHtml(text)}</textarea>`
        : `<p>${escHtml(text || "Not documented.")}</p>`}
    </div>`;
}

function renderClinicalWarnings(soap) {
  const structured = soap?.structured_soap || {};
  const unsupported = Array.isArray(structured.unsupported_claims) ? structured.unsupported_claims : [];
  const flaggedClaims = ["subjective", "objective", "assessment", "plan"]
    .flatMap((section) => Array.isArray(structured[section]) ? structured[section] : [])
    .filter((claim) => claim.status === "UNSUPPORTED");
  const warnings = Array.isArray(structured.warnings) ? structured.warnings : [];
  const messages = [
    ...unsupported.map((claim) => claim.text || "Unsupported clinical statement"),
    ...flaggedClaims.map((claim) => claim.text || "Unsupported clinical statement"),
    ...warnings,
  ];
  if (!messages.length) return "";
  return `<div class="clinical-warning"><strong>Clinician review flag:</strong> ${escHtml(messages.join(" | "))}</div>`;
}

function showSoapEvidence(sectionKey) {
  const claims = Array.isArray(generatedSoap?.structured_soap?.[sectionKey])
    ? generatedSoap.structured_soap[sectionKey]
    : [];
  highlightedEvidenceIds = [...new Set(claims.flatMap((claim) => claim.evidence_ids || []))];
  if (!highlightedEvidenceIds.length) {
    showToast("No transcript source is linked to this section.", "error");
    return;
  }
  if (fullTranscript.length) transcriptMode = "english";
  renderTranscript();
  requestAnimationFrame(() => {
    const target = [...document.querySelectorAll(".transcript-entry")]
      .find((entry) => highlightedEvidenceIds.includes(entry.dataset.utteranceId));
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function renderSoapNote(soap, transcript) {
  if (!soap) {
    renderSoapEmptyState();
    return;
  }

  const patientName = soap.patient_name || selectedPatient?.name || "Unknown patient";
  const date = formatDateTime(soap.visit_date || new Date().toISOString(), { dateOnly: true });
  const saveDisabled = soapSaveBusy || (Boolean(soapLastSavedNoteId) && !soapDraftTouched);
  const canSubmit = Boolean(soapLastSavedNoteId) && !soapDraftTouched && ["AI_DRAFT", "AMENDED", "REJECTED"].includes(generatedNoteState);
  const canReview = Boolean(soapLastSavedNoteId) && generatedNoteState === "REVIEW_REQUIRED";
  const approved = generatedNoteState === "APPROVED_BY_DOCTOR" && !soapDraftTouched && !Object.values(soapSectionEditing).some(Boolean);
  const canCode = Boolean(soapLastSavedNoteId);

  document.getElementById("soapContent").innerHTML = `
    <div class="soap-header">
      <div>
        <h4>SOAP Note</h4>
        <div class="soap-subtitle">${escHtml(patientName)} | ${escHtml(date)} | Generated by ${escHtml(soap.generated_by || "Medflow AI")}</div>
        <div class="summary-pill">${escHtml((generatedNoteState || "AI_DRAFT").replaceAll("_", " "))}</div>
        <div class="soap-save-hint">${escHtml(soapLastSavedNoteId && !soapDraftTouched ? "Saved to the Notes archive." : "Review and edit any section before saving this note.")}</div>
      </div>
      <div class="soap-actions">
        <button class="note-action icon-action" title="Save changes" aria-label="Save note changes" ${saveDisabled ? "disabled" : ""} onclick="saveSoapDraft()">${studioIcon("save")}</button>
        <button class="note-action icon-action" title="Copy approved note" aria-label="Copy approved note" ${approved ? "" : "disabled"} onclick="copySoap()">${studioIcon("copy")}</button>
        <button class="note-action icon-action" title="Download approved note" aria-label="Download approved note" ${approved ? "" : "disabled"} onclick="downloadSoap()">${studioIcon("download")}</button>
        ${canReview ? '<button class="note-action icon-action" title="Return draft for correction" aria-label="Reject draft" onclick="rejectCurrentSoap()">'+studioIcon('undo-2')+'</button>' : ""}
      </div>
    </div>
    ${renderClinicalWarnings(soap)}
    ${renderSoapSection("subjective", "S - Subjective", soap.subjective)}
    ${renderSoapSection("objective", "O - Objective", soap.objective)}
    ${renderSoapSection("assessment", "A - Assessment", soap.assessment)}
    ${renderSoapSection("plan", "P - Plan", soap.plan)}
    `;

  renderTranscript();
  studioIcons();
  renderClinicFlow();
}

function startSoapSectionEdit(sectionKey) {
  if (!generatedSoap || soapSaveBusy) return;
  soapSectionSnapshots[sectionKey] = generatedSoap[sectionKey] || "";
  soapSectionEditing[sectionKey] = true;
  renderSoapNote(generatedSoap, fullTranscript);
  requestAnimationFrame(() => {
    const editor = document.getElementById(`soapEditor_${sectionKey}`);
    if (editor) {
      editor.focus();
      editor.setSelectionRange(editor.value.length, editor.value.length);
    }
  });
}

function updateSoapSectionDraft(sectionKey, value) {
  if (!generatedSoap) return;
  generatedSoap[sectionKey] = String(value || "");
  soapDraftTouched = true;
}

function saveSoapSectionEdit(sectionKey) {
  soapSectionEditing[sectionKey] = false;
  delete soapSectionSnapshots[sectionKey];
  renderSoapNote(generatedSoap, fullTranscript);
}

function cancelSoapSectionEdit(sectionKey) {
  if (generatedSoap && Object.prototype.hasOwnProperty.call(soapSectionSnapshots, sectionKey)) {
    generatedSoap[sectionKey] = soapSectionSnapshots[sectionKey];
  }
  soapSectionEditing[sectionKey] = false;
  delete soapSectionSnapshots[sectionKey];
  renderSoapNote(generatedSoap, fullTranscript);
}

async function saveSoapDraft() {
  if (!generatedSoap) {
    showToast("No SOAP note to save yet.", "error");
    return;
  }

  if (!selectedPatient) {
    showToast("Select a patient before saving the note.", "error");
    return;
  }

  if (soapSaveBusy || (soapLastSavedNoteId && !soapDraftTouched)) {
    return;
  }

  soapSaveBusy = true;
  renderSoapNote(generatedSoap, fullTranscript);

  try {
    const response = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        note_id: soapLastSavedNoteId || null,
        patient: selectedPatient,
        patient_id: selectedPatient._id || "manual",
        soap: generatedSoap,
        transcript: fullTranscript.length ? fullTranscript : diarizedTranscript,
      }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiMessage(payload, "Unable to save the SOAP note."));
    }

    delete afterVisitSummaries[soapLastSavedNoteId];
    soapLastSavedNoteId = payload.note_id || "";
    currentNoteVersion = payload.version || currentNoteVersion;
    generatedNoteState = payload.state || generatedNoteState || "AI_DRAFT";
    // Saved edits get fresh claim IDs/source checks from the server's new version.
    generatedSoap = normalizeSoapDraft(payload.soap || generatedSoap);
    soapDraftTouched = false;
    soapSectionEditing = {};
    soapSectionSnapshots = {};
    upsertSavedNote(payload);
    updateRecordingBanner("SOAP note saved", "The reviewed note has been saved to the Notes page.");
    setWorkspaceStatus("Note saved");
    showToast("SOAP note saved successfully.");
  } catch (error) {
    console.error("Failed to save SOAP note", error);
    showToast(error.message || "Unable to save the SOAP note.", "error");
  } finally {
    soapSaveBusy = false;
    renderSoapNote(generatedSoap, fullTranscript);
    renderPatientAssistant();
  }
}

async function submitSoapForReview() {
  if (!soapLastSavedNoteId || soapDraftTouched) return;
  return await updateNoteState(`/api/notes/${encodeURIComponent(soapLastSavedNoteId)}/submit-for-review`, {}, "Note submitted for doctor review.");
}

async function approveCurrentSoap() {
  if (!soapLastSavedNoteId) return;
  return await updateNoteState(`/api/notes/${encodeURIComponent(soapLastSavedNoteId)}/approve`, {}, "Note approved by the authenticated doctor.");
}

async function rejectCurrentSoap() {
  if (!soapLastSavedNoteId) return;
  const reason = window.prompt("Reason for rejecting this draft:", "Requires correction");
  if (!reason) return;
  await updateNoteState(`/api/notes/${encodeURIComponent(soapLastSavedNoteId)}/reject`, { reason }, "Note rejected for correction.");
}

async function updateNoteState(url, body, successMessage) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to update the note."));
    if (payload.version !== currentNoteVersion) delete afterVisitSummaries[soapLastSavedNoteId];
    generatedNoteState = payload.state || generatedNoteState;
    currentNoteVersion = payload.version || currentNoteVersion;
    generatedSoap = normalizeSoapDraft(payload.soap || generatedSoap);
    upsertSavedNote(payload);
    renderSoapNote(generatedSoap, fullTranscript);
    await refreshActiveContext();
    showToast(successMessage);
    return true;
  } catch (error) {
    showToast(error.message || "Unable to update the note.", "error");
    return false;
  }
}

function upsertSavedNote(note) {
  const existing = savedNotes.filter((item) => item.note_id !== note.note_id);
  savedNotes = [note, ...existing];
  updateNoteStats();
  if (!notesFilterPatientId || notesFilterPatientId === note.patient_id) {
    selectedNoteId = note.note_id;
  }
  renderNotesPage();
  renderPatientAssistant();
}

function setNotesSearch(value) {
  notesSearchQuery = String(value || "").trim().toLowerCase();
  renderNotesPage();
}

function renderNotesPage() {
  const titleEl = document.getElementById("notesTitle");
  const subtitleEl = document.getElementById("notesSubtitle");
  const countEl = document.getElementById("notesCountBadge");
  const listEl = document.getElementById("notesList");

  const filterPatient = notesFilterPatientId
    ? allPatients.find((patient) => patient._id === notesFilterPatientId) || selectedPatient
    : null;

  titleEl.textContent = filterPatient ? `${filterPatient.name || "Patient"} notes` : "All patient notes";
  subtitleEl.textContent = filterPatient
    ? `Showing reviewed notes saved for ${filterPatient.name || "the selected patient"}.`
    : "Every SOAP note you save after review appears here.";

  const items = getVisibleNotes();
  countEl.textContent = `${items.length} record${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    listEl.innerHTML = `
      <div class="empty-state">
        <div>
          <h4>No notes found</h4>
          <p>Generate a SOAP draft from the capture workspace, review it, and save it to populate this archive.</p>
        </div>
      </div>`;
    renderNoteDetail(null);
    return;
  }

  if (!selectedNoteId || !items.some((item) => item.note_id === selectedNoteId)) {
    selectedNoteId = items[0].note_id;
  }

  const groups = groupNotes(items);
  listEl.innerHTML = groups.map((group) => `
    <section>
      <div class="notes-group-label">
        <strong>${group.label}</strong>
        <span>${group.items.length} record${group.items.length === 1 ? "" : "s"}</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;margin-top:12px;">
        ${group.items.map((note) => renderNoteRow(note)).join("")}
      </div>
    </section>`).join("");

  const selected = items.find((item) => item.note_id === selectedNoteId) || items[0];
  renderNoteDetail(selected);
}

function getVisibleNotes() {
  const sortMode = document.getElementById("notesSort")?.value || "newest";
  let items = savedNotes.filter(note => !notesFilterPatientId || note.patient_id === notesFilterPatientId);

  if (notesSearchQuery) {
    items = items.filter((note) => {
      const patientName = (note.patient_name || "").toLowerCase();
      const excerpt = (note.excerpt || "").toLowerCase();
      const subjective = (note.soap?.subjective || "").toLowerCase();
      const assessment = (note.soap?.assessment || "").toLowerCase();
      return patientName.includes(notesSearchQuery)
        || excerpt.includes(notesSearchQuery)
        || subjective.includes(notesSearchQuery)
        || assessment.includes(notesSearchQuery);
    });
  }

  if (sortMode === "patient") {
    items.sort((left, right) => String(left.patient_name || "").localeCompare(String(right.patient_name || "")));
  } else {
    items.sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
  }

  return items;
}

function groupNotes(items) {
  const groups = [
    { label: "Today", items: [] },
    { label: "Previous 7 Days", items: [] },
    { label: "Older", items: [] },
  ];

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  items.forEach((note) => {
    const date = new Date(note.created_at || Date.now());
    const diff = todayStart - new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const days = Math.floor(diff / 86400000);

    if (days <= 0) groups[0].items.push(note);
    else if (days <= 7) groups[1].items.push(note);
    else groups[2].items.push(note);
  });

  return groups.filter((group) => group.items.length);
}

function renderNoteRow(note) {
  const active = selectedNoteId === note.note_id;
  return `
    <button class="note-row ${active ? "active" : ""}" onclick="selectNote('${escAttr(note.note_id)}')">
      <div class="avatar">${getInitials(note.patient_name || "Unknown")}</div>
      <div class="row-copy">
        <strong>${escHtml(note.patient_name || "Unknown")}</strong>
        <span>${escHtml(note.excerpt || "SOAP note available for review.")}</span>
      </div>
      <div class="row-meta">
        <span class="meta-badge">${escHtml((note.state || "AI_DRAFT").replaceAll("_", " "))}</span>
        <span>${formatDateTime(note.created_at)}</span>
      </div>
      <div class="note-chevron">&gt;</div>
    </button>`;
}

function selectNote(noteId) {
  selectedNoteId = noteId;
  renderNotesPage();
}

function renderNoteDetail(note) {
  const container = document.getElementById("noteDetail");
  if (!note) {
    container.innerHTML = `
      <div class="note-empty">
        <div>
          <h4 style="font-size:22px;letter-spacing:-0.04em;margin-bottom:8px;color:var(--ink-1);">Select a saved note</h4>
          <p>Choose a note from the archive to inspect the SOAP sections and transcript preview.</p>
        </div>
      </div>`;
    return;
  }

  const matchingPatient = allPatients.find((patient) => patient._id === note.patient_id) || null;
  const approved = note.state === "APPROVED_BY_DOCTOR";
  const transcriptPreview = Array.isArray(note.transcript)
    ? note.transcript.slice(0, 6)
      .map((entry) => `${speakerDisplayLabel(entry, singleAttendantRelation(note.transcript))}: ${entry.text}`)
      .join("\n")
    : "Transcript preview not available.";

  container.innerHTML = `
    <div class="note-header-band">
      <div class="section-kicker">${escHtml(formatDateTime(note.created_at))}</div>
      <h4>${escHtml(note.patient_name || "Unknown")}</h4>
      <p>${escHtml(note.excerpt || "SOAP note ready for review.")}</p>
    </div>

    <div class="detail-actions">
      <button class="note-action" ${approved ? "" : "disabled"} onclick="copySavedNote('${escAttr(note.note_id)}')">Copy note</button>
      <button class="note-action" ${approved ? "" : "disabled"} onclick="downloadSavedNote('${escAttr(note.note_id)}')">Download</button>
      <button class="note-action" onclick="resumeSavedNote('${escAttr(note.note_id)}')">${approved ? "Open visit" : "Resume review"}</button>
    </div>

    <div class="detail-stat-grid">
      <div class="detail-stat">
        <small>Patient file</small>
        <strong>${escHtml(note.patient_id || "Unknown")}</strong>
      </div>
      <div class="detail-stat">
        <small>Visit date</small>
        <strong>${escHtml(note.soap?.visit_date || formatDateTime(note.created_at, { dateOnly: true }))}</strong>
      </div>
      <div class="detail-stat">
        <small>Clinical status</small>
        <strong>${escHtml((note.state || "AI_DRAFT").replaceAll("_", " "))}</strong>
      </div>
    </div>

    <div class="soap-section">
      <h5>S - Subjective</h5>
      <p>${escHtml(note.soap?.subjective || "Not documented.")}</p>
    </div>
    <div class="soap-section">
      <h5>O - Objective</h5>
      <p>${escHtml(note.soap?.objective || "Not documented.")}</p>
    </div>
    <div class="soap-section">
      <h5>A - Assessment</h5>
      <p>${escHtml(note.soap?.assessment || "Not documented.")}</p>
    </div>
    <div class="soap-section">
      <h5>P - Plan</h5>
      <p>${escHtml(note.soap?.plan || "Not documented.")}</p>
    </div>

    <div class="transcript-preview">
      <h5>Transcript preview</h5>
      <pre>${escHtml(transcriptPreview)}</pre>
    </div>

    ${renderAfterVisitControls(note)}

    <div class="coding-status-panel">
      <h5>ICD-10 &amp; CPT coding</h5>
      <p>Open the coding workspace to generate diagnosis and procedure code suggestions from this note.</p>
      <button class="note-action" type="button" ${workspaceCodingEnabled ? "" : "disabled"} onclick="openCodingForSavedNote('${escAttr(note.note_id)}')">${workspaceCodingEnabled ? "Open coding" : "Coding disabled"}</button>
    </div>`;

  studioIcons();
}

function renderAfterVisitControls(note) {
  if (note.state !== "APPROVED_BY_DOCTOR") {
    return `
      <div class="after-visit-panel">
        <div class="section-kicker">After-visit summary</div>
        <p style="margin-top:7px;color:var(--ink-2);font-size:13px;line-height:1.55;">Available only after an authenticated doctor approves the current note version.</p>
      </div>`;
  }
  const summary = afterVisitSummaries[note.note_id] || null;
  return `
    <div class="after-visit-panel">
      <div class="section-kicker">After-visit summary</div>
      <div class="after-visit-toolbar" style="margin-top:12px;">
        <label>
          Language
          <select id="afterVisitLanguage_${escAttr(note.note_id)}">
            <option value="ENGLISH">English</option>
            <option value="URDU">Urdu</option>
            <option value="BILINGUAL" selected>Bilingual</option>
          </select>
        </label>
        <button class="note-action primary" type="button" onclick="generateAfterVisitSummary('${escAttr(note.note_id)}')">${summary ? "Regenerate" : "Generate"}</button>
        ${summary ? '<button class="note-action" type="button" onclick="printAfterVisitSummary()">Print</button>' : ""}
      </div>
      ${summary ? `
        <div class="after-visit-summary print-target">
          ${(summary.sections || []).map((section) => `
            <section>
              <h6>${escHtml(section.title || "Summary")}</h6>
              <ul>${(section.items || []).map((item) => `<li>${escHtml(item.text || "")}</li>`).join("")}</ul>
            </section>`).join("")}
        </div>` : '<p style="margin-top:12px;color:var(--ink-2);font-size:13px;">Generate from the current doctor-approved version. Draft and rejected notes are never used.</p>'}
    </div>`;
}

async function generateAfterVisitSummary(noteId) {
  const note = savedNotes.find((item) => item.note_id === noteId);
  if (!note || note.state !== "APPROVED_BY_DOCTOR") return;
  const language = document.getElementById(`afterVisitLanguage_${noteId}`)?.value || "BILINGUAL";
  try {
    const response = await fetch(`/api/notes/${encodeURIComponent(noteId)}/after-visit-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to generate the after-visit summary."));
    afterVisitSummaries[noteId] = payload;
    renderNoteDetail(note);
    showToast("After-visit summary generated from the approved note.");
  } catch (error) {
    showToast(error.message || "Unable to generate the after-visit summary.", "error");
  }
}

function printAfterVisitSummary() {
  if (!document.querySelector(".after-visit-summary")) return;
  document.body.classList.add("printing-after-visit");
  const cleanup = () => document.body.classList.remove("printing-after-visit");
  window.addEventListener("afterprint", cleanup, { once: true });
  window.print();
  setTimeout(cleanup, 1000);
}

function getLatestPatientNote(patientId = selectedPatient?._id || "") {
  if (!patientId) return null;
  return savedNotes.find((note) => note.patient_id === patientId && note.state === "APPROVED_BY_DOCTOR") || null;
}

function buildAssistantSuggestions(patient, hasNote) {
  if (!patient) return [];
  const name = patient.name || "this patient";
  const complaint = patient.current_complaint || "the current complaint";
  const prompts = [
    `What is the likely issue with ${name} based on the current patient context?`,
    `Which medicines or treatment directions are supported for ${name} in the current record?`,
    `What follow-up questions or tests would be worth clarifying for ${complaint}?`,
  ];
  if (hasNote) {
    prompts[0] = `What is the likely issue based on ${name}'s latest SOAP note?`;
  }
  return prompts;
}

function renderPatientAssistant() {
  const titleEl = document.getElementById("assistantPatientTitle");
  const subtitleEl = document.getElementById("assistantPatientSubtitle");
  const contextEl = document.getElementById("assistantPatientContext");
  const threadEl = document.getElementById("assistantThread");
  const suggestionsEl = document.getElementById("assistantSuggestions");
  const submitBtn = document.getElementById("assistantSubmitBtn");

  if (!titleEl || !subtitleEl || !contextEl || !threadEl || !suggestionsEl || !submitBtn) {
    return;
  }

  if (!selectedPatient) {
    titleEl.textContent = "Current patient context";
    subtitleEl.textContent = "Select a patient to let the assistant answer questions from intake details and the latest approved SOAP note.";
    contextEl.innerHTML = `
      <div class="assistant-context-card full">
        <small>Status</small>
        <strong>No patient selected</strong>
        <p>Choose a patient from the queue or notes page before asking the assistant about symptoms, SOAP findings, or medications already documented for that patient.</p>
      </div>`;
    suggestionsEl.innerHTML = "";
    threadEl.innerHTML = `
      <div class="empty-state">
        <div>
          <h4>Select a patient first</h4>
          <p>The assistant only answers questions tied to the current patient record and SOAP note.</p>
        </div>
      </div>`;
    submitBtn.disabled = true;
    return;
  }

  const patient = selectedPatient;
  const latestNote = getLatestPatientNote(patient._id || "");
  const hasNote = Boolean(latestNote);

  titleEl.textContent = `${patient.name || "Unknown"} Assistant`;
  subtitleEl.textContent = hasNote
    ? "Grounded in intake and the latest doctor-approved note."
    : "Grounded in intake until a clinical note is approved.";

  contextEl.innerHTML = `
    <div class="assistant-context-card">
      <small>Chief complaint</small>
      <strong>${escHtml(patient.current_complaint || "Not documented")}</strong>
      <p>${escHtml((patient.booking_slot_time || patient.booking_time_slot) ? `Booked slot: ${patient.booking_slot_time || patient.booking_time_slot}. Keep questions tied to this complaint or the resulting SOAP note.` : "Patient-specific questions should stay tied to this complaint or the resulting SOAP note.")}</p>
    </div>`;

  suggestionsEl.innerHTML = buildAssistantSuggestions(patient, hasNote)
    .map((prompt) => `<button class="assistant-chip" type="button" onclick='fillAssistantQuestion(${JSON.stringify(prompt)})'>${escHtml(prompt)}</button>`)
    .join("");

  if (!assistantMessages.length) {
    threadEl.innerHTML = `
      <div class="empty-state">
        <div>
          <h4>No questions yet</h4>
          <p>Ask about likely issues, medications already supported by the note, or how the SOAP note aligns with the current intake record.</p>
        </div>
      </div>`;
  } else {
    threadEl.innerHTML = assistantMessages.map((message) => {
      if (message.role === "user") {
        return `
          <div class="assistant-message user">
            <div class="assistant-meta">
              <span class="assistant-role">Clinician Query</span>
            </div>
            <p>${escHtml(message.text || "")}</p>
          </div>`;
      }

      const status = message.status || "related";
      const statusLabel = status === "unrelated"
        ? "Unrelated"
        : status === "insufficient"
          ? "Limited context"
          : "Patient matched";

      return `
        <div class="assistant-message assistant">
          <div class="assistant-meta">
            <span class="assistant-role">Patient Assistant</span>
            <span class="assistant-status ${escAttr(status)}">${escHtml(statusLabel)}</span>
          </div>
          ${message.summary ? `<div class="assistant-summary">${escHtml(message.summary)}</div>` : ""}
          <p>${escHtml(message.text || "")}</p>
          ${Array.isArray(message.sources) && message.sources.length ? `
            <div class="assistant-sources">
              ${message.sources.map((source) => `<span class="assistant-source">${escHtml(source.replace(/_/g, " "))}</span>`).join("")}
            </div>` : ""}
        </div>`;
    }).join("");
  }

  if (assistantBusy) {
    threadEl.insertAdjacentHTML("beforeend", `
      <div class="assistant-message assistant">
        <div class="assistant-loading"><span class="spinner"></span><span>Reviewing the patient record…</span></div>
      </div>`);
  }

  submitBtn.disabled = assistantBusy;
  document.querySelectorAll('[onclick="clearPatientAssistantChat()"]').forEach(button => {button.disabled = assistantBusy;});
}

function fillAssistantQuestion(value) {
  const input = document.getElementById("assistantQuestion");
  if (!input) return;
  input.value = String(value || "");
  input.focus();
}

function clearPatientAssistantChat() {
  if (assistantBusy) return;
  assistantMessages = [];
  assistantBusy = false;
  renderPatientAssistant();
}

async function askPatientAssistant(event) {
  event.preventDefault();
  if (assistantBusy) return;
  const revision = contextRevision;

  if (!selectedPatient) {
    showToast("Select a patient first.", "error");
    return;
  }

  const input = document.getElementById("assistantQuestion");
  const question = String(input?.value || "").trim();
  if (!question) {
    showToast("Enter a patient-related question first.", "error");
    return;
  }

  assistantMessages.push({ role: "user", text: question });
  assistantBusy = true;
  renderPatientAssistant();
  input.value = "";

  try {
    const response = await fetch("/api/patient-assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: selectedPatient._id || "",
        question,
      }),
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : {};
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error("Patient assistant endpoint is unavailable. Restart the Module 2 server.");
      }
      throw new Error(payload.error || "Assistant request failed.");
    }

    if (revision !== contextRevision) return;
    const result = payload.result || {};
    assistantMessages.push({
      role: "assistant",
      text: result.answer || "I do not have enough patient context to answer that.",
      summary: result.summary || "Patient context reviewed",
      status: result.status || "insufficient",
      sources: Array.isArray(result.sources) ? result.sources : [],
    });
  } catch (error) {
    if (revision !== contextRevision) return;
    console.error("Patient assistant failed", error);
    assistantMessages.push({
      role: "assistant",
      text: error.message || "The patient assistant is unavailable right now.",
      summary: "Assistant unavailable",
      status: "insufficient",
      sources: [],
    });
    showToast("Unable to reach the patient assistant.", "error");
  } finally {
    if (revision === contextRevision) {assistantBusy = false;renderPatientAssistant();}
  }
}

function openNotePatient(patientId) {
  const patient = allPatients.find((item) => item._id === patientId);
  if (!patient) {
    showToast("Patient record not found for this note.", "error");
    return;
  }
  openPatientVisit(patient);
}

function copySoap() {
  if (!generatedSoap) {
    showToast("No SOAP note to copy yet.", "error");
    return;
  }
  if (generatedNoteState !== "APPROVED_BY_DOCTOR") {
    showToast("Doctor approval is required before copying or exporting this note.", "error");
    return;
  }
  navigator.clipboard.writeText(formatSoapText(generatedSoap, selectedPatient?.name || "Unknown patient"))
    .then(() => showToast("SOAP note copied to clipboard."));
}

function downloadSoap() {
  if (!generatedSoap) {
    showToast("No SOAP note to download yet.", "error");
    return;
  }
  if (generatedNoteState !== "APPROVED_BY_DOCTOR") {
    showToast("Doctor approval is required before copying or exporting this note.", "error");
    return;
  }
  downloadText(
    formatSoapText(generatedSoap, selectedPatient?.name || "Unknown patient"),
    `SOAP_${slugify(selectedPatient?.name || "patient")}_${todayStamp()}.txt`
  );
}

function copySavedNote(noteId) {
  const note = savedNotes.find((item) => item.note_id === noteId);
  if (!note) {
    showToast("Saved note not found.", "error");
    return;
  }
  if (note.state !== "APPROVED_BY_DOCTOR") {
    showToast("Doctor approval is required before copying this note.", "error");
    return;
  }
  navigator.clipboard.writeText(formatSoapText(note.soap || {}, note.patient_name || "Unknown patient"))
    .then(() => showToast("Saved note copied to clipboard."));
}

function downloadSavedNote(noteId) {
  const note = savedNotes.find((item) => item.note_id === noteId);
  if (!note) {
    showToast("Saved note not found.", "error");
    return;
  }
  if (note.state !== "APPROVED_BY_DOCTOR") {
    showToast("Doctor approval is required before exporting this note.", "error");
    return;
  }
  downloadText(
    formatSoapText(note.soap || {}, note.patient_name || "Unknown patient"),
    `SOAP_${slugify(note.patient_name || "patient")}_${todayStamp()}.txt`
  );
}

function formatSoapText(soap, patientName) {
  const visitDate = soap.visit_date || todayStamp();
  return [
    `SOAP NOTE`,
    `Patient: ${patientName}`,
    `Date: ${visitDate}`,
    `Generated by: ${soap.generated_by || "Medflow AI"}`,
    ``,
    `S: ${soap.subjective || "Not documented."}`,
    ``,
    `O: ${soap.objective || "Not documented."}`,
    ``,
    `A: ${soap.assessment || "Not documented."}`,
    ``,
    `P: ${soap.plan || "Not documented."}`,
  ].join("\n");
}

function downloadText(text, filename) {
  const blob = new Blob([text], { type: "text/plain" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function showAddPatient() {
  try {
    const response = await fetch("/api/consultation/patients/seed", { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to add synthetic development patients."));
    await fetchPatients();
    showToast("Synthetic development patients are ready.");
  } catch (error) {
    showToast(error.message || "Unable to add synthetic development patients.", "error");
  }
}

function openCodingForSavedNote(noteId) {
  showCodingWorkspace({ noteId: noteId || "", autoGenerate: true });
}

function resolveCodingNote() {
  const noteId = codingNoteId || soapLastSavedNoteId || selectedNoteId || "";
  if (!noteId) return null;
  const archived = savedNotes.find((item) => item.note_id === noteId);
  if (archived) return archived;
  if (generatedSoap && soapLastSavedNoteId === noteId) {
    return {
      note_id: noteId,
      patient_id: selectedPatient?._id || selectedPatient?.patient_id || "",
      patient_name: selectedPatient?.name || generatedSoap.patient_name || "Current patient",
      state: generatedNoteState || "AI_DRAFT",
      soap: generatedSoap,
      created_at: generatedSoap.visit_date || new Date().toISOString(),
    };
  }
  return { note_id: noteId, patient_name: selectedPatient?.name || "Selected note", state: generatedNoteState || "AI_DRAFT", soap: generatedSoap || {} };
}

function renderCodingWorkspace() {
  const note = resolveCodingNote();
  const titleEl = document.getElementById("codingNoteTitle");
  const subtitleEl = document.getElementById("codingNoteSubtitle");
  const summaryEl = document.getElementById("codingNoteSummary");
  const statusEl = document.getElementById("codingStatusPill");
  const generateBtn = document.getElementById("codingGenerateBtn");
  const regenerateBtn = document.getElementById("codingRegenerateBtn");
  if (!titleEl || !summaryEl) return;

  if (!note) {
    titleEl.textContent = "No note selected";
    subtitleEl.textContent = "Generate a SOAP note in Capture, then return here to create ICD-10 and CPT codes.";
    summaryEl.innerHTML = `<div class="empty-state"><p>No SOAP note is ready for coding yet.</p></div>`;
    statusEl.textContent = "Waiting for note";
    generateBtn.disabled = true;
    regenerateBtn.disabled = true;
    document.getElementById("codingResults").innerHTML = `<div class="empty-state"><p>Code suggestions will appear here after generation.</p></div>`;
    return;
  }

  codingNoteId = note.note_id;
  titleEl.textContent = note.patient_name || selectedPatient?.name || "Current note";
  subtitleEl.textContent = `Note ${note.note_id} · ${(note.state || "AI_DRAFT").replaceAll("_", " ")}`;
  statusEl.textContent = codingBusy ? "Generating…" : (codingSuggestions.length ? `${codingSuggestions.length} suggestions` : "Ready");
  generateBtn.disabled = codingBusy || !note.note_id || !workspaceCodingEnabled;
  regenerateBtn.disabled = codingBusy || !note.note_id || !codingSuggestions.length || !workspaceCodingEnabled;
  generateBtn.textContent = codingSuggestions.length ? "Codes ready" : "Generate ICD-10 & CPT codes";

  const soap = note.soap || {};
  summaryEl.innerHTML = `
    <div class="coding-summary-grid">
      <div class="detail-stat"><small>Patient</small><strong>${escHtml(note.patient_name || selectedPatient?.name || "Unknown")}</strong></div>
      <div class="detail-stat"><small>Note state</small><strong>${escHtml((note.state || "AI_DRAFT").replaceAll("_", " "))}</strong></div>
      <div class="detail-stat"><small>Visit date</small><strong>${escHtml(soap.visit_date || formatDateTime(note.created_at, { dateOnly: true }))}</strong></div>
    </div>
    <div class="soap-section"><h5>Assessment</h5><p>${escHtml(soap.assessment || "Not documented.")}</p></div>
    <div class="soap-section"><h5>Plan</h5><p>${escHtml(soap.plan || "Not documented.")}</p></div>`;
  renderCodingResults();
}

function renderCodingResults() {
  const root = document.getElementById("codingResults");
  if (!root) return;
  if (!codingSuggestions.length) {
    root.innerHTML = `<div class="empty-state"><p>${workspaceCodingEnabled ? "No suggestions yet. Generate from the selected SOAP note." : "Clinical coding is disabled in this server configuration."}</p></div>`;
    return;
  }
  const icd = codingSuggestions.filter((item) => String(item.system || "ICD-10").toUpperCase().includes("ICD"));
  const cpt = codingSuggestions.filter((item) => String(item.system || "").toUpperCase().includes("CPT"));
  root.innerHTML = `
    <div class="coding-columns">
      <section class="coding-column">
        <div class="section-kicker">ICD-10</div>
        <h4>Diagnosis codes</h4>
        <div class="coding-list">${icd.length ? icd.map(renderCodingCard).join("") : '<p class="coding-empty">No ICD-10 suggestions.</p>'}</div>
      </section>
      <section class="coding-column">
        <div class="section-kicker">CPT</div>
        <h4>Procedure codes</h4>
        <div class="coding-list">${cpt.length ? cpt.map(renderCodingCard).join("") : '<p class="coding-empty">No CPT suggestions.</p>'}</div>
      </section>
    </div>`;
}

function renderCodingCard(item) {
  const status = String(item.status || "SUGGESTED");
  const pending = status === "SUGGESTED";
  const confidence = Math.round(Number(item.confidence || 0) * 100);
  return `
    <article class="coding-card status-${escAttr(status.toLowerCase())}">
      <div class="coding-card-top">
        <strong>${escHtml(item.code || "")}</strong>
        <span class="summary-pill">${escHtml(status.replaceAll("_", " "))}</span>
      </div>
      <p>${escHtml(item.description || "")}</p>
      <div class="coding-meta">
        <span>${escHtml(item.system || "ICD-10")}</span>
        <span>${confidence}% confidence</span>
        <span>Evidence: ${escHtml((item.evidence_ids || []).join(", ") || "n/a")}</span>
      </div>
      ${pending ? `
        <div class="detail-actions" style="margin-top:12px;">
          <button class="note-action primary" type="button" onclick="reviewCodingSuggestion('${escAttr(item.code_suggestion_id)}', true)">Approve</button>
          <button class="note-action" type="button" onclick="reviewCodingSuggestion('${escAttr(item.code_suggestion_id)}', false)">Reject</button>
        </div>` : ""}
    </article>`;
}

async function loadCodingSuggestions(noteId) {
  if (!noteId || !workspaceCodingEnabled) { codingSuggestions=[];renderCodingWorkspace(); return; }
  try {
    const response = await fetch(`/api/notes/${encodeURIComponent(noteId)}/code-suggestions`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to load code suggestions."));
    codingSuggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
    codingNoteId = noteId;
    renderCodingWorkspace();
  } catch (error) {
    codingSuggestions = [];
    renderCodingWorkspace();
    showToast(error.message || "Unable to load code suggestions.", "error");
  }
}

async function generateCodingSuggestions(force = false) {
  if (!workspaceCodingEnabled) {showToast("Clinical coding is disabled in this server configuration.", "error");return;}
  const note = resolveCodingNote();
  if (!note?.note_id) {
    showToast("Generate a SOAP note before creating ICD-10/CPT codes.", "error");
    return;
  }
  if (codingBusy) return;
  codingBusy = true;
  codingNoteId = note.note_id;
  renderCodingWorkspace();
  setWorkspaceStatus("Generating codes");
  try {
    const query = force ? "?force=true" : "";
    const response = await fetch(`/api/notes/${encodeURIComponent(note.note_id)}/code-suggestions${query}`, {
      method: "POST",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to generate ICD-10/CPT codes."));
    codingSuggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
    showToast(force ? "ICD-10 and CPT codes regenerated." : "ICD-10 and CPT codes generated.");
    setWorkspaceStatus("Codes ready");
    renderCodingWorkspace();
  } catch (error) {
    showToast(error.message || "Unable to generate ICD-10/CPT codes.", "error");
    setWorkspaceStatus("Attention needed");
    renderCodingWorkspace();
  } finally {
    codingBusy = false;
    renderCodingWorkspace();
  }
}

async function reviewCodingSuggestion(suggestionId, approve) {
  if (!suggestionId || codingBusy) return;
  codingBusy = true;
  renderCodingWorkspace();
  try {
    const path = approve ? "approve" : "reject";
    const response = await fetch(`/api/code-suggestions/${encodeURIComponent(suggestionId)}/${path}`, {
      method: "POST",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiMessage(payload, "Unable to review code suggestion."));
    codingSuggestions = codingSuggestions.map((item) => (
      item.code_suggestion_id === suggestionId ? payload : item
    ));
    showToast(approve ? "Code suggestion approved." : "Code suggestion rejected.");
  } catch (error) {
    showToast(error.message || "Unable to review code suggestion.", "error");
  } finally {
    codingBusy = false;
    renderCodingWorkspace();
  }
}

function todayStamp() {
  return new Date().toISOString().slice(0, 10);
}

function getInitials(name) {
  return String(name || "MF").split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "MF";
}

function formatDateTime(value, options = {}) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  if (options.dateOnly) {
    return date.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
  }
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function slugify(value) {
  return String(value || "patient").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "patient";
}

function escHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function apiMessage(payload, fallback) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (payload?.detail && typeof payload.detail.message === "string") return payload.detail.message;
  if (typeof payload?.error === "string") return payload.error;
  if (typeof payload?.message === "string") return payload.message;
  if (Array.isArray(payload?.detail) && payload.detail.length) return "The submitted information is invalid.";
  return fallback;
}

function showToast(message, type = "info") {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.className = `toast${type === "error" ? " error" : ""}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3600);
}

let dashboardReturnRefresh = false;
async function refreshReturnedDashboard(){
  if(dashboardReturnRefresh || !currentUser || typeof visitLocked==='function' && visitLocked())return;
  dashboardReturnRefresh=true;
  try{await refreshDashboardQueues();}finally{dashboardReturnRefresh=false;}
}
window.addEventListener('focus',refreshReturnedDashboard);
window.addEventListener('pageshow',event=>{if(event.persisted)refreshReturnedDashboard();});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refreshReturnedDashboard();});
