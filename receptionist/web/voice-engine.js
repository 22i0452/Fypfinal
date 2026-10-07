/* Local turn endpointing. Signal thresholds are not speech-confidence scores. */
(function (root) {
  "use strict";
  class TurnDetector {
    constructor({ sampleRate = 16000, silenceMs = 1100, maxMs = 25000, preMs = 320 } = {}) {
      Object.assign(this, { sampleRate, silenceMs, maxMs, preMs });
      this.noise = .002;
      this.reset();
    }
    reset() {
      this.pre = []; this.preSamples = 0; this.chunks = [];
      this.started = false; this.onset = 0; this.quiet = 0;
      this.total = 0; this.voiced = 0;
    }
    feed(samples) {
      const frame = new Float32Array(samples);
      const ms = frame.length / this.sampleRate * 1000;
      let power = 0, mean = 0;
      for (const x of frame) mean += x;
      mean /= frame.length || 1;
      for (const x of frame) power += (x - mean) ** 2;
      const rms = Math.sqrt(power / (frame.length || 1));
      const threshold = Math.max(this.started ? .005 : .008, this.noise * (this.started ? 1.6 : 2.8));
      const sound = rms > threshold;
      if (!this.started) {
        this.pre.push(frame); this.preSamples += frame.length;
        while (this.pre.length > 1 && this.preSamples - this.pre[0].length > this.sampleRate * this.preMs / 1000) {
          this.preSamples -= this.pre.shift().length;
        }
        this.onset = sound ? this.onset + ms : 0;
        if (!sound) this.noise = .98 * this.noise + .02 * Math.min(rms, .015);
        if (this.onset >= 40) {
          this.started = true; this.chunks = this.pre; this.pre = [];
          this.total = this.preSamples / this.sampleRate * 1000;
          this.voiced = this.onset; this.preSamples = 0;
          return { started: true };
        }
        return null;
      }
      this.chunks.push(frame); this.total += ms;
      if (sound) { this.voiced += ms; this.quiet = 0; } else this.quiet += ms;
      if (this.total >= this.maxMs) return this.finish("limit");
      if (this.quiet >= this.silenceMs) return this.finish("silence");
      return null;
    }
    finish(reason = "manual") {
      if (!this.started) return null;
      const result = { chunks: this.chunks, sampleRate: this.sampleRate, reason, voicedMs: this.voiced };
      this.reset();
      return result;
    }
  }

  class Conversation {
    constructor(callbacks) {
      this.cb = callbacks; this.phase = "ended"; this.active = false;
      this.paused = false; this.autoInterrupt = false; this.generation = 0;
      this.detector = new TurnDetector(); this.lastFrameAt = 0;
    }
    emit(phase, detail) {
      this.phase = phase; this.cb.onStatus?.(phase, detail);
    }
    async start() {
      this.stop();
      const generation = ++this.generation;
      this.active = true; this.paused = false; this.emit("starting", "Connecting your microphone…");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: {
          channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        } });
        if (!this.active || generation !== this.generation) { stream.getTracks().forEach(t => t.stop()); return false; }
        this.stream = stream;
        const AudioCtx = root.AudioContext || root.webkitAudioContext;
        this.context = new AudioCtx({ sampleRate: 16000 });
        await this.context.resume();
        if (!this.active || generation !== this.generation) return false;
        this.source = this.context.createMediaStreamSource(stream);
        this.detector = new TurnDetector({ sampleRate: this.context.sampleRate });
        // Worklet keeps capture off the main thread. Older browsers retain a bounded fallback.
        if (this.context.audioWorklet && root.AudioWorkletNode) {
          try {
            await this.context.audioWorklet.addModule("/receptionist-static/voice-worklet.js?v=20261007-hands-free");
            if (!this.active || generation !== this.generation) return false;
            this.processor = new AudioWorkletNode(this.context, "medflow-turn-capture");
            this.processor.port.onmessage = e => this.frame(e.data);
          } catch (_) { /* fallback below */ }
        }
        if (!this.active || generation !== this.generation) return false;
        if (!this.processor) {
          this.processor = this.context.createScriptProcessor(1024, 1, 1);
          this.processor.onaudioprocess = e => this.frame(e.inputBuffer.getChannelData(0));
        }
        this.mute = this.context.createGain(); this.mute.gain.value = 0;
        this.source.connect(this.processor); this.processor.connect(this.mute); this.mute.connect(this.context.destination);
        this.lastFrameAt = performance.now();
        for (const track of stream.getTracks()) track.onended = () => { if (this.active) this.fail("Microphone disconnected. Resume or use manual mode."); };
        this.context.onstatechange = () => { if (this.active && this.context?.state === "suspended") this.pause("Microphone suspended. Press Resume when ready."); };
        this.watchdog = setInterval(() => {
          if (this.active && !this.paused && performance.now() - this.lastFrameAt > 5000) this.pause("Microphone stopped responding. Press Resume or switch to manual mode.");
        }, 1500);
        this.hold("processing");
        return true;
      } catch (error) {
        if (generation !== this.generation) return false;
        this.fail(error.message || "Unable to access microphone. Use manual mode or type your answer.");
        return false;
      }
    }
    frame(samples) {
      if (!this.active || this.paused) return;
      this.lastFrameAt = performance.now();
      root.MedFlowMeter?.feed("reception", samples);
      if (performance.now() < (this.listenAfter || 0)) return;
      const interrupt = this.phase === "speaking" && this.autoInterrupt && this.cb.canInterrupt?.();
      if (!interrupt && !["listening", "capturing"].includes(this.phase)) return;
      const event = this.detector.feed(samples);
      if (event?.started) {
        if (interrupt) {
          // Require more sustained signal during playback; this remains an opt-in experiment.
          this.interruptCandidate = true;
        } else this.emit("capturing", "Hearing you · pause naturally to send");
      }
      if (interrupt && this.detector.started && this.detector.voiced >= 240) {
        this.interruptCandidate = false;
        this.cb.onInterrupt?.();
        this.emit("capturing", "Samra stopped · hearing your correction");
      }
      if (event?.chunks && (!interrupt || this.phase === "capturing")) this.submit(event);
    }
    hold(phase = "processing") {
      if (!this.active) return;
      this.pending = null; this.detector.reset(); this.listenAfter = 0;
      if (!this.paused) this.emit(phase, phase === "speaking" ? "Samra is speaking" : "Processing your answer…");
    }
    ready({ review = false } = {}) {
      if (!this.active || this.paused) return;
      if (review) { this.pause("Review the recognized answer, then Resume or send a correction.", "review"); return; }
      if (["capturing", "listening"].includes(this.phase)) return;
      this.detector.reset();
      this.detector.silenceMs = this.cb.silenceMs?.() || 1100;
      this.listenAfter = performance.now() + 250;
      this.emit("listening", "Listening · speak when ready");
    }
    interrupt() {
      if (!this.active || this.paused || !this.cb.canInterrupt?.()) return;
      this.cb.onInterrupt?.(); this.detector.reset(); this.listenAfter = 0;
      this.detector.silenceMs = this.cb.silenceMs?.() || 1100;
      this.emit("listening", "Samra stopped · speak your answer or correction");
    }
    async submit(event) {
      if (!this.active || this.paused || !event) return;
      if (event.reason === "limit") {
        this.pending = event;
        this.pause("Long answer captured. Send it now, or Resume to record again.", "review");
        return;
      }
      const generation = this.generation;
      this.hold();
      try { await this.cb.onTurn(event); }
      catch (error) { if (this.active && generation === this.generation) this.pause(error.message || "Answer failed. Retry or type a correction.", "review"); }
      finally { if (this.active && generation === this.generation) this.ready(); }
    }
    sendNow() {
      if (!this.active) return;
      if (this.pending) {
        const event = this.pending; this.pending = null; this.paused = false;
        this.stream?.getTracks().forEach(t => { t.enabled = true; });
        return this.submit({ ...event, reason: "manual" });
      }
      if (!this.paused && ["listening", "capturing"].includes(this.phase)) return this.submit(this.detector.finish());
    }
    pause(message = "Listening paused · microphone muted", phase = "paused") {
      if (!this.active) return;
      this.paused = true; this.detector.reset();
      this.stream?.getTracks().forEach(t => { t.enabled = false; });
      root.MedFlowMeter?.reset("reception");
      this.emit(phase, message);
    }
    async resume() {
      if (!this.active) return this.start();
      this.pending = null;
      const generation = this.generation;
      try {
        await this.context.resume();
        if (!this.active || generation !== this.generation) return false;
        this.stream.getTracks().forEach(t => { t.enabled = true; });
        this.paused = false; this.lastFrameAt = performance.now(); this.phase = "processing";
        this.ready(); return true;
      } catch (error) { this.fail(error.message || "Microphone could not resume."); return false; }
    }
    fail(message) { this.stop(); this.emit("error", message); this.cb.onError?.(message); }
    stop() {
      ++this.generation; this.active = false; this.paused = false; this.pending = null;
      clearInterval(this.watchdog); this.watchdog = null;
      if (this.processor?.port) this.processor.port.onmessage = null;
      if (this.processor) this.processor.onaudioprocess = null;
      for (const node of [this.processor, this.source, this.mute]) { try { node?.disconnect(); } catch (_) {} }
      this.stream?.getTracks().forEach(t => { t.onended = null; t.stop(); });
      if (this.context) { this.context.onstatechange = null; this.context.close().catch(() => {}); }
      this.processor = this.source = this.mute = this.stream = this.context = null;
      this.detector.reset(); root.MedFlowMeter?.reset("reception");
      this.emit("ended", "Hands-free microphone off");
    }
  }
  const exports = { TurnDetector, Conversation };
  root.MedFlowVoice = exports;
  if (typeof module !== "undefined") module.exports = exports;
})(typeof window !== "undefined" ? window : globalThis);
