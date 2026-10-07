/* Optional receptionist hands-free controls. Manual Mic/Stop remains the default. */
(function () {
  "use strict";
  let enabled = false;
  try { enabled = localStorage.getItem("medflow.handsFree") === "on"; } catch (_) {}
  let lastReply = null;
  const labels = { ended: "Ready", starting: "Connecting", listening: "Listening", capturing: "Hearing you", processing: "Processing", speaking: "Samra speaking", paused: "Paused", review: "Review answer", error: "Microphone off" };
  const controller = new MedFlowVoice.Conversation({
    onTurn: async event => {
      const pcm = resampleFloat32(mergeFloat32Chunks(event.chunks), event.sampleRate, 16000);
      await submitDemoAudio(encodeWavMono16(pcm, 16000), { automatic: true });
    },
    silenceMs: () => {
      if (agentArtifact?.step === "confirm" || agentArtifact?.step === "summary") return 850;
      return ["phone", "history", "complaint", "time"].includes(agentArtifact?.current_field) ? 1600 : 1100;
    },
    canInterrupt: () => state.demoRunning && !state.demoCompleting && !!state.demoAudio,
    onInterrupt: () => stopDemoAudio(),
    onStatus: (phase, detail) => {
      render(phase, detail);
      if (controller.active && !["processing", "speaking"].includes(phase)) {
        window.receptionPhase?.(phase === "capturing" ? "listening" : phase, detail);
      }
    },
    onError: message => { showToast(message, "error"); setDemoComposerEnabled(state.demoRunning); },
  });

  function render(phase = controller.phase, detail) {
    const panel = document.getElementById("liveVoiceControls"); if (!panel) return;
    panel.closest(".demo-runner-panel")?.classList.toggle("hands-free-mode", supported());
    panel.hidden = state.demoMode !== "voice" || state.selectedDemoId !== "in-new-booking";
    document.getElementById("handsFreeToggle").checked = enabled;
    document.getElementById("handsFreeToggle").disabled = state.demoBusy || state.demoSaving || state.demoRecording;
    const status = document.getElementById("liveVoiceStatus");
    status.dataset.phase = phase;
    status.textContent = !enabled ? "Manual Mic / Stop" : labels[phase] || "Ready";
    if (detail) document.getElementById("liveVoiceDetail").textContent = detail;
    else if (!enabled) document.getElementById("liveVoiceDetail").textContent = "Your existing microphone controls are available below.";
    else if (!state.demoRunning) document.getElementById("liveVoiceDetail").textContent = "Start the call once, then speak and pause naturally. Audio is sent after each completed turn.";
    document.getElementById("liveVoiceActions").hidden = !enabled || !state.demoRunning;
    const pause = document.getElementById("liveVoicePause");
    pause.textContent = controller.paused || !controller.active ? "Resume listening" : "Pause listening";
    pause.disabled = state.demoBusy || state.demoCompleting || controller.phase === "starting";
    document.getElementById("liveVoiceInterrupt").disabled = !controller.active || !state.demoAudio || state.demoCompleting || controller.paused;
    document.getElementById("liveVoiceSend").disabled = !controller.pending && (controller.paused || controller.phase !== "capturing");
    document.getElementById("liveVoiceRepeat").disabled = state.demoBusy || state.demoCompleting || controller.phase === "starting" || !lastReply;
    document.getElementById("autoInterruptToggle").disabled = state.demoBusy || !enabled;
    document.getElementById("autoInterruptOption").hidden = !enabled;
    const mic = document.getElementById("demoMicBtn");
    if (mic) mic.hidden = enabled && state.selectedDemoId === "in-new-booking";
    const hint = document.getElementById("demoVoiceHint");
    if (hint) hint.textContent = enabled && state.selectedDemoId === "in-new-booking" ? "Hands-free: pause naturally to send. Use Pause, Send now, or edit the transcript if needed." : "Voice call: tap Mic to reply, then Stop to send. Typing remains available.";
  }
  function supported() { return enabled && state.demoMode === "voice" && state.selectedDemoId === "in-new-booking"; }
  async function startIfEnabled() {
    if (!supported() || !state.demoRunning) return;
    stopDemoMic();
    const connected = await controller.start();
    if (connected && state.demoRunning && !state.demoBusy) controller.ready();
    return connected;
  }
  window.setHandsFree = async checked => {
    if (state.demoBusy || state.demoSaving || state.demoRecording) { render(); return; }
    enabled = !!checked;
    try { localStorage.setItem("medflow.handsFree", enabled ? "on" : "off"); } catch (_) {}
    controller.stop();
    render();
    if (supported() && state.demoRunning) await startIfEnabled();
  };
  window.setAutoInterrupt = checked => { controller.autoInterrupt = !!checked; controller.detector.reset(); };
  window.pauseLiveVoice = async () => {
    if (state.demoBusy || state.demoCompleting || controller.phase === "starting") return;
    if (!controller.active) { await startIfEnabled(); return; }
    if (controller.paused) await controller.resume(); else controller.pause();
    render();
  };
  window.interruptLiveVoice = () => { controller.interrupt(); render(); };
  window.sendLiveVoiceNow = () => controller.sendNow();
  window.repeatLiveQuestion = async () => {
    if (!state.demoRunning || state.demoBusy || !lastReply) return;
    const epoch = state.demoSessionId;
    state.demoBusy = true; controller.hold(); setDemoComposerEnabled(false);
    try { await playDemoSpeech(lastReply.speech, lastReply.reply); }
    catch (error) { if (demoSessionAlive(epoch)) showToast(error.message || "Playback failed", "error"); }
    finally { if (demoSessionAlive(epoch)) { state.demoBusy = false; setDemoComposerEnabled(true); controller.ready(); } }
  };
  window.liveConversation = {
    controller, supported, render, startIfEnabled,
    hold: phase => { if (supported()) controller.hold(phase); },
    ready: review => { if (supported()) controller.ready({ review }); render(); },
    pause: message => { if (supported()) controller.pause(message, "review"); },
    stop: () => { controller.stop(); lastReply = null; render(); },
    remember: (speech, reply) => { lastReply = { speech, reply }; render(); },
    capturing: () => controller.active && controller.phase === "capturing",
  };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && controller.active) { stopDemoAudio(); controller.pause("Conversation paused while the page is in the background. Press Resume to continue."); }
  });
  window.addEventListener("offline", () => { if (controller.active) { stopDemoAudio(); controller.pause("Connection lost. Your accepted details remain here. Resume when connected.", "review"); } });
  window.addEventListener("pagehide", () => stopDemo());
  document.addEventListener("DOMContentLoaded", () => render());
})();
