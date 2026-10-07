/* Twenty-millisecond PCM frames; the output is intentionally silent. */
class MedFlowTurnCapture extends AudioWorkletProcessor {
  constructor() { super(); this.size = Math.round(sampleRate * .02); this.frame = new Float32Array(this.size); this.offset = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) for (let i = 0; i < input.length; i++) {
      this.frame[this.offset++] = input[i];
      if (this.offset === this.size) {
        this.port.postMessage(this.frame, [this.frame.buffer]);
        this.frame = new Float32Array(this.size); this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("medflow-turn-capture", MedFlowTurnCapture);
