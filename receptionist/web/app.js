const state = {
  config: null,
  intakeToken: "",
  revision: 1,
  patientId: "",
  workflowId: "",
  appointmentId: "",
  bookingReceipt: null,
  lastSpeech: null,
  busy: false,
  view: "intake",
  clinicNumber: "",
  liveCalls: [],
  selectedCallId: "",
  liveTimer: null,
  demoDirection: "inbound",
  selectedDemoId: "",
  demoMode: "voice",
  demoRunning: false,
  demoSessionId: 0,
  demoAbort: null,
  demoSpeechAbort: null,
  demoPlaybackResolve: null,
  demoSpeechId: 0,
  demoCompleting: false,
  demoBusy: false,
  demoHistory: [],
  demoSaving: false,
  demoSaved: null,
  demoRecorder: null,
  demoRecording: false,
  demoAudio: null,
  demoStream: null,
  demoAudioContext: null,
  demoProcessor: null,
  demoMute: null,
  demoSource: null,
  demoPcmChunks: [],
};

const DEMO_SCENARIOS = {
  inbound: [
    {
      id: "in-new-booking",
      title: "New appointment",
      summary: "Patient calls to book first appointment",
      description:
        "Live inbound demo: you speak/type as the new patient; Samra collects booking details turn by turn.",
    },
    {
      id: "in-existing-booking",
      title: "Returning patient",
      summary: "Existing patient calls to book follow-up or new appointment",
      description:
        "Live inbound demo: returning patient identity + follow-up/new visit booking with Samra.",
    },
    {
      id: "in-cancel",
      title: "Cancellation",
      summary: "Patient calls to cancel existing appointment",
      description:
        "Live inbound demo: cancel an appointment and optionally ask to reschedule.",
    },
  ],
  outbound: [
    {
      id: "out-reminder-24h",
      title: "24-hour reminder",
      summary: "Appointment details, patient contact, location info",
      description:
        "Live outbound demo: Samra starts with a 24-hour reminder; you reply as the patient.",
    },
    {
      id: "out-followup",
      title: "Follow-up",
      summary: "Symptom check after the doctor plan; escalate if worsening",
      description:
        "Live outbound demo: symptom follow-up; worsening triggers clinical flag + rebook offer.",
    },
    {
      id: "out-noshow",
      title: "Missed appointment",
      summary: "Missed appointment record, patient contact, next available slots",
      description:
        "Live outbound demo: recover a missed appointment and book the next slot.",
    },
  ],
};

const FIELDS = [
  "fieldName",
  "fieldAge",
  "fieldPhone",
  "fieldFirstVisit",
  "fieldHistory",
  "fieldComplaint",
  "fieldDepartment",
  "fieldDoctor",
  "fieldVisitType",
  "fieldSlot",
];

function showToast(message, type = "ok") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = `toast show${type === "error" ? " error" : ""}`;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.className = "toast";
  }, 3200);
}

function setStatus(text) {
  document.getElementById("sessionStatus").textContent = text;
}

function clearChatEmptyHint() {
  const hint = document.getElementById("chatEmptyHint");
  if (hint) hint.remove();
}

function addBubble(role, text) {
  clearChatEmptyHint();
  const thread = document.getElementById("chatThread");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.innerHTML = `<span class="meta">${role === "agent" ? "Samra · Receptionist" : "System"}</span>${escapeHtml(text)}`;
  thread.appendChild(bubble);
  thread.scrollTop = thread.scrollHeight;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function apiMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    return String(detail.message || detail.code || fallback);
  }
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(apiMessage(payload, "Request failed"));
  }
  return payload;
}

function randomToken() {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function updateProgress() {
  const filled = FIELDS.filter((id) => String(document.getElementById(id).value || "").trim()).length;
  document.getElementById("progressPill").textContent = typeof intakeStage === "undefined" ? `${filled} / ${FIELDS.length}` : ["Patient details", "Appointment", "Sent to doctor"][intakeStage];
}

function practitionersForDepartment(departmentId) {
  return (state.config?.practitioners || []).filter(
    (item) => !departmentId || item.department_id === departmentId
  );
}

function fillSelect(select, items, getValue, getLabel, placeholder) {
  select.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  select.appendChild(first);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = getValue(item);
    option.textContent = getLabel(item);
    select.appendChild(option);
  }
}

function onDepartmentChange() {
  const departmentId = document.getElementById("fieldDepartment").value;
  fillSelect(
    document.getElementById("fieldDoctor"),
    practitionersForDepartment(departmentId),
    (item) => item.practitioner_id,
    (item) => item.display_name,
    "Select doctor"
  );
  document.getElementById("fieldSlot").innerHTML = '<option value="">Select doctor & visit type first</option>';
  updateProgress();
}

function onDoctorChange() {
  loadSlots();
  updateProgress();
}

function setPanelVisible(el, visible) {
  if (!el) return;
  el.classList.toggle("active", visible);
  if (visible) {
    el.hidden = false;
    el.removeAttribute("hidden");
    el.style.display = "";
  } else {
    el.hidden = true;
    el.setAttribute("hidden", "");
  }
}

function showView(view) {
  const next = view === "demo" || view === "live" || view === "intake" ? view : "intake";
  state.view = next;
  if (next !== "demo" && window.liveConversation?.controller.active) {
    stopDemoAudio(); window.liveConversation.controller.pause("Conversation paused while you are away. Resume to continue.");
  }

  setPanelVisible(document.getElementById("viewIntake"), next === "intake");
  setPanelVisible(document.getElementById("viewDemo"), next === "demo");
  setPanelVisible(document.getElementById("viewLive"), next === "live");

  const navIntake = document.getElementById("navIntake");
  const navDemo = document.getElementById("navDemo");
  const navLive = document.getElementById("navLive");
  if (navIntake) navIntake.classList.toggle("active", next === "intake");
  if (navDemo) navDemo.classList.toggle("active", next === "demo");
  if (navLive) navLive.classList.toggle("active", next === "live");

  if (next === "live") {
    refreshLiveCalls();
    setStatus("Listening for inbound calls");
    return;
  }
  if (next === "demo") {
    try {
      renderDemoScenarios();
    } catch (error) {
      console.error("Demo Call render failed", error);
      showToast(error.message || "Demo Call failed to render", "error");
    }
    setStatus("Demo Call ready");
    return;
  }
  setStatus("Ready");
}

function setDemoDirection(direction) {
  state.demoDirection = direction === "outbound" ? "outbound" : "inbound";
  state.selectedDemoId = "";
  stopDemo();
  hideDemoResult();
  document.getElementById("demoTabInbound").classList.toggle("active", state.demoDirection === "inbound");
  document.getElementById("demoTabOutbound").classList.toggle("active", state.demoDirection === "outbound");
  document.getElementById("demoDirectionPill").textContent =
    state.demoDirection === "outbound" ? "Outbound" : "Inbound";
  document.getElementById("demoRunnerTitle").textContent = "Select a scenario";
  document.getElementById("demoRunnerMeta").textContent =
    "Start chat or voice call demo. Samra replies in Urdu + English.";
  document.getElementById("demoRunnerDetails").hidden = true;
  document.getElementById("demoComposer").hidden = true;
  const voiceHintReset = document.getElementById("demoVoiceHint");
  if (voiceHintReset) voiceHintReset.hidden = true;
  document.getElementById("demoTranscript").innerHTML =
    '<div class="live-empty">Choose a scenario on the left, then start a live interactive demo.</div>';
  renderDemoScenarios();
}

function renderDemoScenarios() {
  const list = document.getElementById("demoScenarioList");
  if (!list) {
    throw new Error("Demo scenario list is missing from the page");
  }
  const scenarios = DEMO_SCENARIOS[state.demoDirection] || [];
  if (!scenarios.length) {
    list.innerHTML = '<div class="live-empty">No demo scenarios available.</div>';
    return;
  }
  list.innerHTML = scenarios
    .map((item) => {
      const active = item.id === state.selectedDemoId ? "active" : "";
      return `<button class="demo-scenario-card ${active}" type="button" onclick="selectDemoScenario('${item.id}')">
        <div class="demo-scenario-top">
          <strong>${escapeHtml(item.title)}</strong>
          <span class="demo-chip">${escapeHtml(state.demoDirection)}</span>
        </div>
        <p>${escapeHtml(item.summary)}</p>
      </button>`;
    })
    .join("");
}

function getSelectedDemo() {
  const scenarios = DEMO_SCENARIOS[state.demoDirection] || [];
  return scenarios.find((item) => item.id === state.selectedDemoId) || null;
}

function selectDemoScenario(scenarioId) {
  stopDemo();
  hideDemoResult();
  state.selectedDemoId = scenarioId;
  const scenario = getSelectedDemo();
  renderDemoScenarios();
  if (!scenario) return;

  document.getElementById("demoRunnerTitle").textContent = scenario.title;
  document.getElementById("demoRunnerMeta").textContent = scenario.summary;
  document.getElementById("demoRunnerDescription").textContent = scenario.description;
  document.getElementById("demoRunnerDetails").hidden = false;
  document.getElementById("demoLiveBtn").hidden = state.demoDirection !== "inbound";
  document.getElementById("demoComposer").hidden = true;
  const voiceHint = document.getElementById("demoVoiceHint");
  if (voiceHint) voiceHint.hidden = true;
  setDemoMode(state.demoMode || "chat");
  document.getElementById("demoTranscript").innerHTML =
    '<div class="live-empty">Choose <strong>Chat demo</strong> or <strong>Voice call</strong>, then reply as the caller.</div>';
  setStatus(`Demo · ${scenario.title}`);
}

function setDemoMode(mode) {
  const nextMode = mode === "voice" ? "voice" : "chat";
  if (state.demoMode !== nextMode) window.liveConversation?.stop();
  state.demoMode = nextMode;
  const chatTab = document.getElementById("demoModeChat");
  const voiceTab = document.getElementById("demoModeVoice");
  if (chatTab) chatTab.classList.toggle("active", state.demoMode === "chat");
  if (voiceTab) voiceTab.classList.toggle("active", state.demoMode === "voice");
  const runBtn = document.getElementById("demoRunBtn");
  const voiceBtn = document.getElementById("demoVoiceBtn");
  if (runBtn) runBtn.hidden = state.demoMode !== "chat";
  if (voiceBtn) voiceBtn.hidden = state.demoMode !== "voice";
  window.liveConversation?.render();
}

function splitBilingualDisplay(text) {
  const raw = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!raw) return { urdu: "", english: "" };
  const lines = raw.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length >= 2) {
    return { urdu: lines[0], english: lines.slice(1).join(" ") };
  }
  const arabic = /[\u0600-\u06FF]/;
  if (arabic.test(raw) && /[A-Za-z]/.test(raw)) {
    const urduBits = [];
    const engBits = [];
    const runRe =
      /(?:[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF][\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\s\u060C\u061B\u061F،؟.!،:؛\-—0-9]*)|(?:[A-Za-z][A-Za-z0-9\s,'\-\.?!:;/%]*)/g;
    let m;
    while ((m = runRe.exec(raw)) !== null) {
      const chunk = m[0].trim();
      if (!chunk) continue;
      if (arabic.test(chunk)) urduBits.push(chunk);
      else engBits.push(chunk);
    }
    return {
      urdu: urduBits.join(" ").trim(),
      english: engBits.join(" ").trim(),
    };
  }
  if (arabic.test(raw)) return { urdu: raw, english: "" };
  return { urdu: "", english: raw };
}

function appendDemoLine(role, text) {
  const thread = document.getElementById("demoTranscript");
  if (thread.querySelector(".live-empty")) thread.innerHTML = "";
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role === "agent" ? "agent" : "patient"}`;
  const meta = role === "agent" ? "Samra · Agent" : "You · Caller";
  if (role === "agent") {
    const parts = splitBilingualDisplay(text);
    let body = "";
    if (parts.urdu) {
      body += `<div class="bilingual-urdu" dir="rtl" lang="ur">${escapeHtml(parts.urdu)}</div>`;
    }
    if (parts.english) {
      body += `<div class="bilingual-en" dir="ltr" lang="en">${escapeHtml(parts.english)}</div>`;
    }
    if (!body) body = escapeHtml(text);
    bubble.innerHTML = `<span class="meta">${meta}</span>${body}`;
  } else {
    bubble.innerHTML = `<span class="meta">${meta}</span>${escapeHtml(text)}`;
  }
  thread.appendChild(bubble);
  thread.scrollTop = thread.scrollHeight;
}

function setDemoComposerEnabled(enabled) {
  const input = document.getElementById("demoInput");
  const sendBtn = document.getElementById("demoSendBtn");
  const micBtn = document.getElementById("demoMicBtn");
  if (input) {
    input.disabled = !enabled || state.demoBusy;
    input.hidden = false;
  }
  if (sendBtn) {
    sendBtn.disabled = !enabled || state.demoBusy;
    sendBtn.hidden = false;
  }
  if (micBtn) micBtn.disabled = !enabled || state.demoBusy;
  window.renderReceptionDoctorChoices?.();
  window.liveConversation?.render();
}

function stopDemoAudio() {
  const playing = state.demoAudio;
  state.demoSpeechId += 1;
  state.demoSpeechAbort?.abort();
  state.demoSpeechAbort = null;
  const settle = state.demoPlaybackResolve;
  state.demoPlaybackResolve = null;
  settle?.();
  if (playing) {
    try {
      playing.pause();
      playing.src = "";
    } catch (_) {
      /* ignore */
    }
  }
  state.demoAudio = null;
}

function mergeFloat32Chunks(chunks) {
  let total = 0;
  for (const chunk of chunks) total += chunk.length;
  const merged = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function resampleFloat32(input, fromRate, toRate) {
  if (!input.length || fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const outLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const src = i * ratio;
    const i0 = Math.floor(src);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const t = src - i0;
    output[i] = input[i0] * (1 - t) + input[i1] * t;
  }
  return output;
}

function encodeWavMono16(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function stopDemoMicCapture({ finalize = false } = {}) {
  if (state.demoProcessor) {
    try {
      state.demoProcessor.disconnect();
    } catch (_) {
      /* ignore */
    }
  }
  if (state.demoSource) {
    try {
      state.demoSource.disconnect();
    } catch (_) {
      /* ignore */
    }
  }
  if (state.demoMute) {
    try {
      state.demoMute.disconnect();
    } catch (_) {
      /* ignore */
    }
  }
  if (state.demoStream) {
    state.demoStream.getTracks().forEach((track) => track.stop());
  }
  const ctx = state.demoAudioContext;
  const chunks = state.demoPcmChunks || [];
  const sampleRate = ctx ? ctx.sampleRate : 16000;
  state.demoProcessor = null;
  state.demoSource = null;
  state.demoMute = null;
  state.demoStream = null;
  state.demoPcmChunks = [];
  state.demoRecording = false;
  window.MedFlowMeter?.reset("reception");
  const micBtn = document.getElementById("demoMicBtn");
  if (micBtn) micBtn.textContent = "Mic";
  if (ctx) {
    try {
      ctx.close();
    } catch (_) {
      /* ignore */
    }
  }
  state.demoAudioContext = null;
  if (!finalize) return null;
  if (!chunks.length) return null;
  const merged = mergeFloat32Chunks(chunks);
  const pcm16k = resampleFloat32(merged, sampleRate, 16000);
  if (pcm16k.length < 16000 * 0.06) return null;
  return encodeWavMono16(pcm16k, 16000);
}

function stopDemoMic() {
  if (state.demoRecorder && state.demoRecording) {
    try {
      state.demoRecorder.stop();
    } catch (_) {
      /* ignore */
    }
  }
  stopDemoMicCapture({ finalize: false });
  state.demoRecording = false;
  window.MedFlowMeter?.reset("reception");
  const micBtn = document.getElementById("demoMicBtn");
  if (micBtn) micBtn.textContent = "Mic";
}

function stopDemo() {
  state.demoSessionId += 1;
  state.demoAbort?.abort();
  state.demoAbort = null;
  state.demoCompleting = false;
  window.liveConversation?.stop();
  stopDemoMic();
  stopDemoAudio();
  state.demoRunning = false;
  state.demoBusy = false;
  state.demoHistory = [];
  const stopBtn = document.getElementById("demoStopBtn");
  const runBtn = document.getElementById("demoRunBtn");
  const voiceBtn = document.getElementById("demoVoiceBtn");
  const composer = document.getElementById("demoComposer");
  const voiceHint = document.getElementById("demoVoiceHint");
  if (stopBtn) stopBtn.hidden = true;
  if (runBtn) runBtn.disabled = false;
  if (voiceBtn) voiceBtn.disabled = false;
  if (composer) composer.hidden = true;
  if (voiceHint) voiceHint.hidden = true;
  setDemoComposerEnabled(false);
  setDemoMode(state.demoMode || "chat");
}

function hideDemoResult() {
  state.demoSaved = null;
  const box = document.getElementById("demoResult");
  if (box) {
    box.hidden = true;
    box.innerHTML = "";
  }
}

// End the call and save what Samra collected as a patient intake + booking.
async function endDemo() {
  if (state.demoSaving) return;
  const scenario = getSelectedDemo();
  const history = state.demoHistory || [];
  stopDemo();
  if (!scenario || scenario.id !== "in-new-booking" || !history.length) {
    setStatus("Demo ended");
    return;
  }
  state.demoSaving = true;
  setStatus("Saving patient details…");
  try {
    const result = await api("/api/desk/demo-calls/finish", {
      method: "POST",
      body: JSON.stringify({ scenario_id: scenario.id, history }),
    });
    renderDemoResult(result);
    if (result.saved) {
      showToast(`Patient saved · ${result.patient_id}`);
      setStatus("Demo ended · patient saved");
    } else {
      setStatus("Demo ended · not saved");
    }
  } catch (error) {
    showToast(error.message || "Unable to save the demo call", "error");
    setStatus("Demo ended · save failed");
  } finally {
    state.demoSaving = false;
  }
}

function formatSlot(iso) {
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return String(iso || "");
  return value.toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: state.config?.clinic?.timezone || "Asia/Karachi",
  });
}

function demoBookingHtml(booking) {
  if (!booking) return "";
  const status = booking.status;
  if (status === "REQUESTED" || status === "BOOKED") {
    const appointment = booking.appointment || {};
    return `<div class="demo-booking ok">
      <strong>Appointment ${escapeHtml(status === "BOOKED" ? "booked" : "requested")}</strong>
      ${escapeHtml(formatSlot(appointment.start_at))} · ${escapeHtml(appointment.practitioner_name || "Assigned doctor")}
      · ${escapeHtml(appointment.visit_type_name || "")}
      <span>Appointment ${escapeHtml(appointment.appointment_id || "")} · Status ${escapeHtml(appointment.status || status)}</span>
    </div>`;
  }
  if (status === "ALTERNATIVES_REQUIRED") {
    const options = (booking.alternatives || [])
      .map(
        (item, index) => `<button class="note-action" type="button" onclick="bookDemoAlternative(${index})">
          ${escapeHtml(formatSlot(item.start_at))} · ${escapeHtml(item.practitioner_name || "")}
        </button>`
      )
      .join("");
    return `<div class="demo-booking warn">
      <strong>Requested time not available</strong>
      The caller asked for ${escapeHtml(booking.requested_time || "a time")}, which is outside open clinic slots.
      ${options ? `Book one of these instead:<div class="demo-alternatives">${options}</div>` : "No open slots in the next 14 days."}
    </div>`;
  }
  return `<div class="demo-booking warn"><strong>Appointment not booked</strong>${escapeHtml(
    booking.message || "Book the appointment from the Intake tab."
  )}</div>`;
}

function renderDemoResult(result) {
  const box = document.getElementById("demoResult");
  state.demoSaved = result;
  if (!box || !result || !result.supported) {
    if (box) box.hidden = true;
    return;
  }
  const rows = (result.details || [])
    .map(
      (row) => `<div class="demo-detail">
        <span>${escapeHtml(row.label)}</span>
        <strong>${escapeHtml(row.en)}</strong>
        ${row.ur && row.ur !== row.en ? `<em dir="rtl" lang="ur">${escapeHtml(row.ur)}</em>` : ""}
      </div>`
    )
    .join("");
  let heading;
  let note;
  if (result.saved) {
    heading = "Patient saved";
    const forwarded = Boolean(result.booking?.appointment?.appointment_id);
    note = `Patient <strong>${escapeHtml(result.patient_id)}</strong> is saved. ${forwarded ? "The appointment request is visible to the assigned doctor." : "An appointment still needs to be selected. Continue with this saved intake below."}`;
  } else if (result.error) {
    heading = "Patient not saved";
    note = escapeHtml(result.error);
  } else {
    heading = "Call ended before the intake was complete";
    note = `Not saved. Still missing: ${escapeHtml((result.missing || []).join(", "))}.`;
  }
  box.classList.toggle("warn", !result.saved);
  box.innerHTML = `
    <h4>${escapeHtml(heading)}</h4>
    <p>${note}</p>
    ${rows ? `<div class="demo-details">${rows}</div>` : ""}
    ${result.saved ? demoBookingHtml(result.booking) : ""}`;
  box.hidden = false;
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function bookDemoAlternative(index) {
  const saved = state.demoSaved;
  const option = saved?.booking?.alternatives?.[index];
  if (!saved || !option) return;
  setStatus("Booking selected slot…");
  try {
    const booking = await api("/api/desk/bookings", {
      method: "POST",
      body: JSON.stringify({
        patient_id: saved.patient_id,
        workflow_id: saved.workflow_id,
        department_id: option.department_id,
        practitioner_id: option.practitioner_id || "",
        visit_type_id: option.visit_type_id,
        start_at: option.start_at,
        idempotency_key: `demo-alt-${saved.intake_token}-${option.start_at}`,
        intake_token: saved.intake_token,
        revision: saved.revision,
      }),
    });
    saved.booking = { ...booking, requested_time: saved.booking.requested_time };
    renderDemoResult(saved);
    showToast(booking.status === "ALTERNATIVES_REQUIRED" ? "That slot was just taken — pick another." : "Appointment requested.");
    setStatus("Demo ended · patient saved");
  } catch (error) {
    showToast(error.message || "Unable to book the slot", "error");
    setStatus("Booking failed");
  }
}

function demoSessionAlive(epoch) {
  return state.demoRunning && state.demoSessionId === epoch;
}

async function playDemoSpeech(speechText, fullReply) {
  const text = String(speechText || fullReply || "").trim();
  if (!text || !state.demoRunning) return;
  stopDemoAudio();
  const epoch = state.demoSessionId, speechId = state.demoSpeechId;
  const abort = new AbortController(); state.demoSpeechAbort = abort;
  window.liveConversation?.remember(speechText, fullReply);
  window.liveConversation?.hold("processing");
  setStatus("Preparing Samra’s voice…");
  let tts;
  try {
    tts = await api("/api/desk/demo-calls/tts", {
      method: "POST", signal: abort.signal,
      body: JSON.stringify({ text: fullReply || text }),
    });
  } catch (error) { if (abort.signal.aborted || !demoSessionAlive(epoch)) return; throw error; }
  if (!demoSessionAlive(epoch) || speechId !== state.demoSpeechId || !tts.audio_url) return;
  await new Promise((resolve, reject) => {
    const audio = new Audio(tts.audio_url);
    state.demoAudio = audio;
    const settle = error => {
      audio.onplaying = audio.onended = audio.onerror = null;
      if (state.demoAudio === audio) state.demoAudio = null;
      if (state.demoPlaybackResolve === cancel) state.demoPlaybackResolve = null;
      error ? reject(error) : resolve();
    };
    const cancel = () => settle();
    state.demoPlaybackResolve = cancel;
    audio.onplaying = () => {
      window.liveConversation?.hold("speaking");
      window.receptionPhase?.("speaking", "Audio playback active");
      window.liveConversation?.render();
    };
    audio.onended = () => settle();
    audio.onerror = () => settle(new Error("Unable to play Samra audio"));
    audio.play().catch(error => settle(error));
  });
  if (state.demoSpeechAbort === abort) state.demoSpeechAbort = null;
}

async function beginDemoSession({ voice }) {
  if (state.demoSaving) return;
  const scenario = getSelectedDemo();
  if (!scenario) {
    showToast("Select a demo scenario first.", "error");
    return;
  }
  stopDemo();
  hideDemoResult();
  setDemoMode(voice ? "voice" : "chat");
  state.demoRunning = true;
  state.demoAbort = new AbortController();
  const epoch = state.demoSessionId;
  state.demoBusy = true;
  document.getElementById("demoTranscript").innerHTML = "";
  document.getElementById("demoStopBtn").hidden = false;
  document.getElementById("demoRunBtn").disabled = true;
  document.getElementById("demoVoiceBtn").disabled = true;
  document.getElementById("demoComposer").hidden = false;
  const voiceHint = document.getElementById("demoVoiceHint");
  if (voiceHint) voiceHint.hidden = !voice;
  setDemoComposerEnabled(false);
  setStatus(voice ? `Starting voice call · ${scenario.title}` : `Starting chat demo · ${scenario.title}`);

  try {
    if (voice) await window.liveConversation?.startIfEnabled();
    if (!demoSessionAlive(epoch)) return;
    const started = await api("/api/desk/demo-calls/start", {
      signal: state.demoAbort?.signal,
      method: "POST",
      body: JSON.stringify({ scenario_id: scenario.id }),
    });
    if (!demoSessionAlive(epoch)) return;
    state.demoHistory = started.history || [];
    state.lastSpeech = null;
    renderSpeechUnderstanding(null);
    window.receptionArtifact?.(started.process);
    appendDemoLine("agent", started.reply || "");
    if (voice) {
      try {
        await playDemoSpeech(started.speech_text, started.reply);
      } catch (ttsError) {
        showToast(ttsError.message || "TTS playback failed — you can still use Mic", "error");
      }
    }
    if (!demoSessionAlive(epoch)) return;
    state.demoBusy = false;
    setDemoComposerEnabled(true);
    window.liveConversation?.ready(false);
    if (!voice) document.getElementById("demoInput").focus();
    setStatus(voice ? `Voice call · ${scenario.title} · tap Mic to reply` : `Chat demo · ${scenario.title} · your turn`);
    showToast(voice ? (window.liveConversation?.supported() ? "Conversation started — speak and pause naturally." : "Voice call started — Samra spoke; tap Mic to reply.") : "Chat demo started — reply as the caller.");
  } catch (error) {
    if (!demoSessionAlive(epoch)) return;
    stopDemo();
    showToast(error.message || "Unable to start demo", "error");
    setStatus("Demo failed");
  }
}

async function runSelectedDemo() {
  await beginDemoSession({ voice: false });
}

async function runSelectedDemoVoice() {
  await beginDemoSession({ voice: true });
}

async function sendDemoMessage(event) {
  if (event) event.preventDefault();
  if (!state.demoRunning || state.demoBusy) return;
  const scenario = getSelectedDemo();
  if (!scenario) return;
  const input = document.getElementById("demoInput");
  const text = String(input.value || "").trim();
  if (!text) return;

  const epoch = state.demoSessionId;
  let needsReview = false;
  window.liveConversation?.hold();
  input.value = "";
  state.lastSpeech = null;
  appendDemoLine("patient", text);
  state.demoBusy = true;
  setDemoComposerEnabled(false);
  setStatus("Samra is thinking…");

  try {
    const result = await api("/api/desk/demo-calls/turn", {
      signal: state.demoAbort?.signal,
      method: "POST",
      body: JSON.stringify({
        scenario_id: scenario.id,
        user_message: text,
        history: state.demoHistory,
      }),
    });
    if (!demoSessionAlive(epoch)) return;
    state.demoHistory = result.history || state.demoHistory;
    needsReview = !!result.understanding?.needs_review;
    state.demoCompleting = !!result.booking_complete;
    renderSpeechUnderstanding(result.understanding);
    if (result.understanding?.needs_review) input.value = text;
    window.receptionArtifact?.(result.process);
    appendDemoLine("agent", result.reply || "");
    if (state.demoMode === "voice") {
      try {
        await playDemoSpeech(result.speech_text, result.reply);
      } catch (ttsError) {
        showToast(ttsError.message || "TTS playback failed", "error");
      }
      setStatus(`Voice call · ${scenario.title} · tap Mic to reply`);
    } else {
      setStatus(`Chat demo · ${scenario.title} · your turn`);
    }
    if (!demoSessionAlive(epoch)) return;
    if (result.booking_complete) {
      // The caller confirmed the summary: the call is over, so save it.
      state.demoBusy = false;
      await endDemo();
      return;
    }
  } catch (error) {
    if (!demoSessionAlive(epoch)) return;
    needsReview = true;
    input.value = text;
    window.liveConversation?.pause("Answer could not be processed. Retry or edit your answer; accepted details are retained.");
    appendDemoLine(
      "agent",
      "معذرت، جواب نہیں آ سکا۔ دوبارہ کوشش کریں۔\nSorry, I could not reply. Please try again."
    );
    showToast(error.message || "Demo reply failed", "error");
    setStatus("Demo reply failed");
  } finally {
    if (demoSessionAlive(epoch)) {
      state.demoBusy = false;
      setDemoComposerEnabled(true);
      window.liveConversation?.ready(needsReview);
      if (state.demoMode !== "voice") input.focus();
    }
  }
}

async function submitDemoAudio(wavBlob, { automatic = false } = {}) {
  if (!state.demoRunning || state.demoBusy) return;
  const epoch = state.demoSessionId;
  const captureGeneration = window.liveConversation?.controller.generation;
  const alive = () => demoSessionAlive(epoch) && (!automatic || captureGeneration === window.liveConversation?.controller.generation);
  state.demoBusy = true; setDemoComposerEnabled(false);
  window.receptionPhase?.("speech", "Transcribing your completed answer");
  const sttStarted = performance.now();
  try {
    const form = new FormData();
    form.append("audio", wavBlob, "demo-caller.wav");
    form.append("history", JSON.stringify(state.demoHistory));
    const response = await fetch("/api/desk/demo-calls/stt", { method: "POST", body: form, signal: state.demoAbort?.signal });
    const payload = await response.json().catch(() => ({}));
    if (!alive()) return;
    if (!response.ok) throw new Error(apiMessage(payload, "STT failed"));
    window.receptionSttResult?.(payload, performance.now() - sttStarted);
    state.lastSpeech = payload;
    renderSpeechUnderstanding({ raw: payload.raw_text || payload.text || "", needs_review: payload.needs_review, reason: payload.reason });
    const text = String(payload.text || "").trim();
    if (payload.needs_review || payload.garbled || !text) {
      document.getElementById("demoInput").value = payload.raw_text || text;
      window.liveConversation?.pause("Review the recognized words, retry, or type. Accepted details are retained.");
      window.receptionPhase?.("review", "Review the recognized answer; collected details are retained");
      showToast(payload.hint || "Review the recognized words, retry, or type.", "error");
      return;
    }
    document.getElementById("demoInput").value = text;
    state.demoBusy = false;
    await sendDemoMessage();
  } catch (error) {
    if (!alive()) return;
    window.liveConversation?.pause("Transcription failed. Resume to retry or type your answer.");
    window.receptionPhase?.("error", error.message || "Speech transcription failed");
    showToast(error.message || "Mic transcription failed", "error");
  } finally {
    if (demoSessionAlive(epoch)) {
      state.demoBusy = false; setDemoComposerEnabled(true);
      if (!automatic && !window.receptionIsError?.() && !state.lastSpeech?.needs_review) window.receptionPhase?.("ready", "Tap the microphone to reply");
    }
  }
}

async function toggleDemoMic() {
  if (!state.demoRunning || state.demoBusy || window.liveConversation?.supported()) return;
  if (state.demoRecording) {
    const wavBlob = stopDemoMicCapture({ finalize: true });
    if (!wavBlob) {
      showToast("No speech captured. Hold Mic a bit longer and speak clearly.", "error");
      return;
    }
    await submitDemoAudio(wavBlob);
    return;
  }
  stopDemoAudio();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showToast("Microphone is not available in this browser.", "error");
    return;
  }
  const epoch = state.demoSessionId;
  state.demoBusy = true;
  setDemoComposerEnabled(false);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (!demoSessionAlive(epoch)) { stream.getTracks().forEach(t => t.stop()); return; }
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const ctx = new AudioCtx({ sampleRate: 16000 });
    if (ctx.state === "suspended") await ctx.resume();
    if (!demoSessionAlive(epoch)) { stream.getTracks().forEach(t => t.stop()); await ctx.close(); return; }
    const source = ctx.createMediaStreamSource(stream);
    const processor = ctx.createScriptProcessor(1024, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    const chunks = [];
    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      chunks.push(new Float32Array(input));
      window.MedFlowMeter?.feed("reception", input);
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(ctx.destination);
    state.demoStream = stream;
    state.demoAudioContext = ctx;
    state.demoSource = source;
    state.demoProcessor = processor;
    state.demoMute = mute;
    state.demoPcmChunks = chunks;
    state.demoRecording = true;
    document.getElementById("demoMicBtn").textContent = "Stop";
    window.receptionPhase?.("listening", "Speak in Urdu, then tap Stop");
    setStatus("Listening… speak clearly in Urdu, then tap Stop");
  } catch (error) {
    if (!demoSessionAlive(epoch)) return;
    stopDemoMicCapture({ finalize: false });
    showToast(error.message || "Unable to access microphone", "error");
  } finally {
    if (demoSessionAlive(epoch)) { state.demoBusy = false; setDemoComposerEnabled(true); }
  }
}

async function loadConfiguration() {
  setStatus("Loading clinic…");
  state.config = await api("/api/desk/configuration");
  fillSelect(
    document.getElementById("fieldDepartment"),
    state.config.departments || [],
    (item) => item.department_id,
    (item) => item.name,
    "Select department"
  );
  fillSelect(
    document.getElementById("fieldVisitType"),
    state.config.visit_types || [],
    (item) => item.visit_type_id,
    (item) => item.name,
    "Select visit type"
  );
  const preferred = (state.config.practitioners || []).find(x => x.practitioner_id === state.config.preferred_practitioner_id);
  if (preferred) document.getElementById("fieldDepartment").value = preferred.department_id;
  onDepartmentChange();
  if (preferred) {
    document.getElementById("fieldDoctor").value = preferred.practitioner_id;
    document.getElementById("fieldVisitType").value = "VISIT-NEW";
    await loadSlots();
  }
  const clinicName = state.config.clinic?.name || "Medflow Clinic";
  document.getElementById("backendStatus").textContent = "Connected";
  if (!document.getElementById("backendHint").dataset.locked) {
    document.getElementById("backendHint").textContent = `${clinicName} · ${state.config.clinic?.timezone || "local"}`;
  }
  setStatus("Ready");
}

async function loadSlots() {
  const practitionerId = document.getElementById("fieldDoctor").value;
  const visitTypeId = document.getElementById("fieldVisitType").value;
  const slotSelect = document.getElementById("fieldSlot");
  if (!practitionerId || !visitTypeId) {
    slotSelect.innerHTML = '<option value="">Select doctor & visit type first</option>';
    updateProgress();
    return;
  }
  try {
    setStatus("Loading slots…");
    const data = await api(
      `/api/desk/availability?practitioner_id=${encodeURIComponent(practitionerId)}&visit_type_id=${encodeURIComponent(visitTypeId)}&days=14&limit=12`
    );
    if(document.getElementById("fieldDoctor").value!==practitionerId || document.getElementById("fieldVisitType").value!==visitTypeId)return;
    fillSelect(
      slotSelect,
      data.slots || [],
      (item) => item.start_at,
      (item) => item.label || item.start_at,
      "Select booking slot"
    );
    if (!(data.slots || []).length) {
      showToast("No open slots for this doctor/visit type.", "error");
    }
    setStatus("Ready");
  } catch (error) {
    slotSelect.innerHTML = '<option value="">Unable to load slots</option>';
    showToast(error.message || "Unable to load slots", "error");
    setStatus("Attention needed");
  }
  updateProgress();
}

function collectIntakePayload() {
  return {
    name: document.getElementById("fieldName").value.trim(),
    age_text: document.getElementById("fieldAge").value.trim(),
    phone_number: document.getElementById("fieldPhone").value.trim(),
    first_visit: document.getElementById("fieldFirstVisit").value.trim(),
    past_medical_history: document.getElementById("fieldHistory").value.trim(),
    current_complaint: document.getElementById("fieldComplaint").value.trim(),
    intake_token: state.intakeToken,
    revision: state.revision,
    confirmed_revision: state.revision,
  };
}

async function submitIntake(event) {
  event.preventDefault();
  if (state.busy) return;

  const departmentId = document.getElementById("fieldDepartment").value;
  const practitionerId = document.getElementById("fieldDoctor").value;
  const visitTypeId = document.getElementById("fieldVisitType").value;
  const startAt = document.getElementById("fieldSlot").value;
  if (!departmentId || !practitionerId || !visitTypeId || !startAt) {
    showToast("Select department, doctor, visit type, and slot.", "error");
    return;
  }

  state.busy = true;
  document.getElementById("submitBtn").disabled = true;
  setStatus("Submitting…");
  addBubble("system", "Submitting intake and creating a booking request…");

  try {
    const intake = await api("/api/desk/intakes", {
      method: "POST",
      body: JSON.stringify(collectIntakePayload()),
    });
    state.patientId = intake.patient_id;
    state.workflowId = intake.workflow_id;
    state.revision = Number(intake.revision || state.revision);

    const booking = await api("/api/desk/bookings", {
      method: "POST",
      body: JSON.stringify({
        patient_id: state.patientId,
        workflow_id: state.workflowId,
        department_id: departmentId,
        practitioner_id: practitionerId,
        visit_type_id: visitTypeId,
        start_at: startAt,
        idempotency_key: `web-${state.intakeToken}-${startAt}`,
        intake_token: state.intakeToken,
        revision: state.revision,
      }),
    });

    if (booking.status === "ALTERNATIVES_REQUIRED") {
      renderIntakeAlternatives(booking); setStatus("Choose another appointment"); return;
    }
    const appointmentId = booking.appointment?.appointment_id || booking.appointment_id;
    if (!appointmentId) throw new Error("Intake saved, but no appointment was created. Choose a slot and retry.");
    state.appointmentId = appointmentId;
    state.bookingReceipt = booking;
    const result = document.getElementById("bookingResult");
    result.hidden = false;
    result.innerHTML = `
      <h4>Booking request sent</h4>
      <p>
        Patient <strong>${escapeHtml(document.getElementById("fieldName").value)}</strong>
        was forwarded for doctor review.
        Appointment: <strong>${escapeHtml(appointmentId)}</strong>
        · Status: <strong>${escapeHtml(booking.status || "REQUESTED")}</strong>
        · Workflow: <strong>${escapeHtml(booking.workflow_state || intake.workflow_state || "REQUESTED")}</strong>
      </p>`;
    addBubble(
      "agent",
      "شکریہ! مریض کا ریکارڈ اور ملاقات کی درخواست محفوظ کر دی گئی ہے۔ اگلا مریض کے لیے New session دبائیں۔"
    );
    showToast("Intake submitted and booking requested.");
    setStatus("Complete");
  } catch (error) {
    addBubble("system", error.message || "Submission failed.");
    showToast(error.message || "Submission failed.", "error");
    setStatus("Attention needed");
  } finally {
    state.busy = false;
    document.getElementById("submitBtn").disabled = false;
  }
}

function selectLiveCall(callControlId) {
  state.selectedCallId = callControlId || "";
  renderLiveCalls();
}

function renderLiveCalls() {
  const list = document.getElementById("liveCallList");
  const transcript = document.getElementById("liveTranscript");
  const calls = state.liveCalls || [];
  const liveCount = calls.filter((c) => c.status === "active" || c.status === "ringing").length;
  document.getElementById("liveCountPill").textContent = `${liveCount} live`;
  document.getElementById("liveNavHint").textContent =
    liveCount > 0 ? `${liveCount} active inbound call(s)` : "Inbound Urdu transcripts";

  if (!calls.length) {
    list.innerHTML = `<div class="live-empty">No calls yet. Dial <strong>${escapeHtml(
      state.clinicNumber || "the clinic Telnyx number"
    )}</strong> to start.</div>`;
  } else {
    list.innerHTML = calls
      .map((call) => {
        const active = call.call_control_id === state.selectedCallId ? "active" : "";
        const preview = (call.transcript || []).slice(-1)[0]?.text || "Waiting for speech…";
        return `<button class="live-call-item ${active}" type="button" onclick='selectLiveCall(${JSON.stringify(
          call.call_control_id
        )})'>
          <div class="live-call-top">
            <strong>${escapeHtml(call.from_number || "Unknown caller")}</strong>
            <span class="live-status ${escapeHtml(call.status)}">${escapeHtml(call.status)}</span>
          </div>
          <div class="live-call-preview">${escapeHtml(preview)}</div>
        </button>`;
      })
      .join("");
  }

  const selected =
    calls.find((c) => c.call_control_id === state.selectedCallId) ||
    calls.find((c) => c.status === "active" || c.status === "ringing") ||
    calls[0];
  if (selected && selected.call_control_id !== state.selectedCallId) {
    state.selectedCallId = selected.call_control_id;
  }

  if (!selected) {
    document.getElementById("liveTranscriptTitle").textContent = "Select a call";
    document.getElementById("liveTranscriptMeta").textContent =
      "Live patient ↔ Samra dialogue appears here.";
    transcript.innerHTML = `<div class="live-empty">Transcript will stream here during an inbound call.</div>`;
    return;
  }

  document.getElementById("liveTranscriptTitle").textContent = selected.from_number || "Inbound call";
  document.getElementById("liveTranscriptMeta").textContent = `${selected.status} · to ${
    selected.to_number || state.clinicNumber || "clinic"
  }${selected.speaking ? " · Samra speaking" : selected.processing ? " · Processing caller turn" : " · Listening"}`;
  window.renderPhoneProcess?.(selected);
  const lines = selected.transcript || [];
  if (!lines.length) {
    transcript.innerHTML = `<div class="live-empty">Connected — waiting for first utterance…</div>`;
    return;
  }
  transcript.innerHTML = lines
    .map((line) => {
      const role = line.role === "agent" ? "agent" : "patient";
      const label = role === "agent" ? "Samra" : "Caller";
      return `<div class="chat-bubble ${role}${line.interim ? " interim" : ""}">
        <span class="meta">${label}${line.interim ? " · listening" : ""}</span>
        ${escapeHtml(line.text)}
      </div>`;
    })
    .join("");
  transcript.scrollTop = transcript.scrollHeight;
}

async function refreshLiveCalls() {
  try {
    const data = await api("/api/desk/live-calls");
    state.liveCalls = data.calls || [];
    if (state.view === "live") {
      renderLiveCalls();
    } else {
      const liveCount = state.liveCalls.filter((c) => c.status === "active" || c.status === "ringing").length;
      document.getElementById("liveNavHint").textContent =
        liveCount > 0 ? `${liveCount} active inbound call(s)` : "Inbound Urdu transcripts";
    }
  } catch (_) {
    // keep last snapshot if polling fails briefly
  }
}

function resetSession() {
  stopDemo();
  state.intakeToken = randomToken();
  state.revision = 1;
  state.patientId = "";
  state.workflowId = "";
  state.appointmentId = "";
  state.bookingReceipt = null;
  document.getElementById("intakeForm").reset();
  document.getElementById("bookingResult").hidden = true;
  document.getElementById("chatThread").innerHTML =
    '<div class="live-empty" id="chatEmptyHint">No conversation yet. Submit an intake below, or open <strong>Demo Call</strong> to run receptionist scenarios.</div>';
  showView("intake");
  if (state.config) {
    onDepartmentChange();
    fillSelect(
      document.getElementById("fieldVisitType"),
      state.config.visit_types || [],
      (item) => item.visit_type_id,
      (item) => item.name,
      "Select visit type"
    );
  }
  updateProgress();
  setStatus("Ready");
}

async function boot() {
  state.intakeToken = randomToken();
  FIELDS.forEach((id) => {
    document.getElementById(id).addEventListener("input", updateProgress);
    document.getElementById(id).addEventListener("change", updateProgress);
  });
  updateProgress();

  try {
    const health = await api("/api/desk/health");
    state.clinicNumber = health.clinic_number || health.inbound_calls?.clinic_number || "";
    if (state.clinicNumber) {
      document.getElementById("liveClinicHint").textContent =
        `Call ${state.clinicNumber} — Samra answers in Urdu and this panel shows the live transcript.`;
    }
    if (!health.token_configured) {
      document.getElementById("backendStatus").textContent = "Token missing";
      showToast("Receptionist service token is not configured.", "error");
    } else if (health.inbound_calls?.configured) {
      const hint = document.getElementById("backendHint");
      hint.textContent = `Inbound Telnyx ready${state.clinicNumber ? ` · ${state.clinicNumber}` : ""}`;
      hint.dataset.locked = "1";
    }
  } catch (_) {
    document.getElementById("backendStatus").textContent = "Offline";
  }

  try {
    await loadConfiguration();
    renderDemoScenarios();
  } catch (error) {
    document.getElementById("backendStatus").textContent = "Backend offline";
    document.getElementById("backendHint").textContent =
      "Start the clinic API on port 8000, then refresh this page.";
    showToast(error.message || "Unable to load clinic configuration.", "error");
    setStatus("Backend offline");
  }

  state.liveTimer = setInterval(refreshLiveCalls, 1500);
  refreshLiveCalls();
}

boot();

function renderSpeechUnderstanding(answer) {
  const box = document.getElementById("speechUnderstanding");
  if (!box) return;
  box.hidden = !answer;
  if (!answer) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="speech-review-heading"><i data-lucide="scan-text"></i><strong>${answer.needs_review ? "Review your answer" : "Your answer, understood"}</strong></div>
    <dl><dt>Recognized words</dt><dd dir="auto">${escapeHtml(answer.raw || "No microphone signal")}</dd>
    ${answer.ur ? `<dt>Interpreted Urdu</dt><dd dir="auto">${escapeHtml(answer.ur)}</dd>` : ""}
    ${answer.en ? `<dt>English</dt><dd>${escapeHtml(answer.en)}</dd>` : ""}</dl>
    ${answer.needs_review ? '<p>Edit the reply below and press Send, or tap Mic to retry. Previously collected details are retained.</p>' : ''}`;
  if (window.lucide) lucide.createIcons();
}

function resumeDemoIntake(){
  const saved=state.demoSaved;
  if(!saved?.saved || state.busy || state.demoBusy || state.demoSaving)return;
  state.intakeToken=saved.intake_token;state.revision=saved.revision || 1;
  state.patientId=saved.patient_id;state.workflowId=saved.workflow_id;
  state.appointmentId="";state.bookingReceipt=null;
  const ids={name:'fieldName',age:'fieldAge',phone:'fieldPhone',first_visit:'fieldFirstVisit',history:'fieldHistory',complaint:'fieldComplaint'};
  for(const row of saved.details || [])if(ids[row.key])document.getElementById(ids[row.key]).value=row.key==='first_visit'?row.en.toLowerCase():row.en;
  const department=(state.config?.departments || []).find(item=>item.name===(saved.details || []).find(row=>row.key==='department')?.en);
  if(department)document.getElementById('fieldDepartment').value=department.department_id;
  onDepartmentChange();
  const preferred=practitionersForDepartment(document.getElementById('fieldDepartment').value).find(item=>item.practitioner_id===state.config?.preferred_practitioner_id);
  if(preferred)document.getElementById('fieldDoctor').value=preferred.practitioner_id;
  document.getElementById('fieldVisitType').value=(saved.details || []).find(row=>row.key==='first_visit')?.en==='Yes'?'VISIT-NEW':'VISIT-FOLLOWUP';
  if(!document.getElementById('fieldVisitType').value)document.getElementById('fieldVisitType').selectedIndex=1;
  document.getElementById('bookingResult').hidden=true;
  showView('intake');setIntakeStage(1);loadSlots();
}
