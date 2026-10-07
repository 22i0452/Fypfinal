import io
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
import tkinter as tk
import tkinter.font as tkfont
from dotenv import load_dotenv
from tkinter import messagebox, scrolledtext, ttk

sys_path_added = False
try:
    from security_guardrails import Actor, get_gateway
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys_path_added = True
    from security_guardrails import Actor, get_gateway


load_dotenv()


GROQ_MODELS = [
    "whisper-large-v3-turbo",
    "whisper-large-v3",
]

OPENAI_MODELS = [
    "whisper-1",
]

URDU_LANGUAGE_CODE = "ur"
URDU_STT_PROMPT = "یہ آڈیو اردو گفتگو پر مشتمل ہے۔ متن کو قدرتی اردو رسم الخط میں نقل کریں۔"
RTL_MARK = "\u200f"
TRANSCRIPT_PLACEHOLDER = "Start recording, speak in Urdu, then press End Recording to see the transcript."

URDU_FONT_CANDIDATES = [
    ("Noto Nastaliq Urdu", 16),
    ("Jameel Noori Nastaleeq", 16),
    ("Mehr Nastaliq Web", 16),
    ("Nirmala UI", 15),
    ("Segoe UI", 13),
]


@dataclass
class AppConfig:
    sample_rate: int = 16000
    channels: int = 1


class LiveRecorder:
    def __init__(self, config: AppConfig):
        self.config = config
        self.status_queue: queue.Queue[str] = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._audio_frames: list[np.ndarray] = []
        self._audio_lock = threading.Lock()

    def start(self) -> None:
        if self._stream is not None:
            return

        with self._audio_lock:
            self._audio_frames = []

        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()
        self.status_queue.put("Recording started")

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.empty((0, self.config.channels), dtype="float32")

        self._stream.stop()
        self._stream.close()
        self._stream = None

        with self._audio_lock:
            if self._audio_frames:
                recording = np.concatenate(self._audio_frames, axis=0)
            else:
                recording = np.empty((0, self.config.channels), dtype="float32")
            self._audio_frames = []

        self.status_queue.put("Recording stopped")
        return recording

    def _audio_callback(self, indata, frames, callback_time, status) -> None:
        if status:
            self.status_queue.put(f"Audio warning: {status}")
        with self._audio_lock:
            self._audio_frames.append(indata.copy())


class SpeechClient:
    def __init__(self):
        self._actor = Actor(actor_id="reference-stt", role="system_agent")

    def get_models(self, provider: str) -> list[str]:
        if provider == "Groq":
            return GROQ_MODELS
        return OPENAI_MODELS

    def transcribe(self, audio_bytes: bytes, provider: str, model: str, language: str = URDU_LANGUAGE_CODE) -> str:
        provider_name = provider.lower()
        return get_gateway().transcribe_audio(
            task_type="module2_stt",
            audio_bytes=audio_bytes,
            actor=self._actor,
            provider=provider_name,
            model=model,
            language=language,
            prompt=URDU_STT_PROMPT,
            response_format="text",
        )


class LiveTranscriberApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Urdu STT Recorder")
        self.root.geometry("900x560")
        self.root.minsize(820, 500)

        self.config = AppConfig()
        self.recorder = LiveRecorder(self.config)
        self.speech_client = SpeechClient()
        self.ui_status_queue: queue.Queue[str] = queue.Queue()
        self.transcript_queue: queue.Queue[str] = queue.Queue()
        self._transcription_thread: Optional[threading.Thread] = None
        self._recording = threading.Event()
        self._transcribing = threading.Event()
        self.urdu_font_family, self.urdu_font_size = self._resolve_urdu_font()

        self.provider_var = tk.StringVar(value="Groq")
        self.model_var = tk.StringVar(value=GROQ_MODELS[0])
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self._refresh_ui_from_queues()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.root.configure(bg="#f4efe7")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f4efe7")
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 22), background="#f4efe7", foreground="#1f2937")
        style.configure("Body.TLabel", font=("Segoe UI", 10), background="#f4efe7", foreground="#374151")
        style.configure("TButton", font=("Segoe UI", 10), padding=8)
        style.configure("TCombobox", padding=6)

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")

        ttk.Label(header, text="Urdu STT Recorder", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Start recording, speak in Urdu, then end recording to see the transcript.",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 12))

        ttk.Label(controls, text="Provider", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.provider_combo = ttk.Combobox(controls, textvariable=self.provider_var, values=["Groq", "OpenAI"], state="readonly", width=14)
        self.provider_combo.grid(row=0, column=1, sticky="w")
        self.provider_combo.bind("<<ComboboxSelected>>", self._update_models)

        ttk.Label(controls, text="Urdu STT Model", style="Body.TLabel").grid(row=0, column=2, sticky="w", padx=(20, 8))
        self.model_combo = ttk.Combobox(controls, textvariable=self.model_var, values=GROQ_MODELS, state="readonly", width=28)
        self.model_combo.grid(row=0, column=3, sticky="w")

        ttk.Label(
            controls,
            text="Transcription language is fixed to Urdu.",
            style="Body.TLabel",
        ).grid(row=0, column=4, columnspan=2, sticky="w", padx=(20, 0))

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(0, 12))

        self.start_button = ttk.Button(button_row, text="Start Recording", command=self.start_transcription)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text="End Recording", command=self.stop_transcription)
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(button_row, text="Clear Transcript", command=self.clear_transcript).pack(side="left")

        ttk.Label(button_row, textvariable=self.status_var, style="Body.TLabel").pack(side="right")

        transcript_frame = ttk.Frame(outer, padding=10)
        transcript_frame.pack(fill="both", expand=True)

        ttk.Label(transcript_frame, text="Urdu Transcript", style="Body.TLabel").pack(anchor="w")
        ttk.Label(
            transcript_frame,
            text="The transcript appears after you stop recording.",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(4, 6))
        self.transcript_box = scrolledtext.ScrolledText(
            transcript_frame,
            wrap="word",
            font=(self.urdu_font_family, self.urdu_font_size),
            bg="#fffdf8",
            fg="#111827",
            insertbackground="#111827",
            relief="flat",
            padx=12,
            pady=12,
        )
        self.transcript_box.pack(fill="both", expand=True, pady=(6, 0))
        self.transcript_box.tag_configure(
            "caption_meta",
            font=("Segoe UI", 9),
            foreground="#6b7280",
            justify="left",
            spacing1=4,
            spacing3=8,
        )
        self.transcript_box.tag_configure(
            "caption_urdu",
            justify="right",
            rmargin=12,
            lmargin1=12,
            lmargin2=12,
            spacing1=6,
            spacing3=10,
        )
        self._set_transcript_placeholder()
        self._sync_controls()

    def _resolve_urdu_font(self) -> tuple[str, int]:
        available_fonts = {font_name.casefold(): font_name for font_name in tkfont.families(self.root)}
        for family, size in URDU_FONT_CANDIDATES:
            matched_font = available_fonts.get(family.casefold())
            if matched_font:
                return matched_font, size
        return "Segoe UI", 13

    def _set_transcript_placeholder(self, message: str = TRANSCRIPT_PLACEHOLDER) -> None:
        self.transcript_box.delete("1.0", tk.END)
        self.transcript_box.insert(tk.END, f"{message}\n", "caption_meta")

    def _display_transcript(self, transcript: str) -> None:
        cleaned_transcript = transcript.replace("\r", " ").replace("\n", " ").strip()
        if not cleaned_transcript:
            self._set_transcript_placeholder("No speech was detected. Record again and speak a little closer to the microphone.")
            return

        timestamp = time.strftime("%H:%M:%S")
        self.transcript_box.delete("1.0", tk.END)
        self.transcript_box.insert(tk.END, f"{timestamp}\n", "caption_meta")
        self.transcript_box.insert(tk.END, f"{RTL_MARK}{cleaned_transcript}\n", "caption_urdu")
        self.transcript_box.see(tk.END)

    def _update_models(self, event=None) -> None:
        models = self.speech_client.get_models(self.provider_var.get())
        self.model_combo["values"] = models
        self.model_var.set(models[0])

    def start_transcription(self) -> None:
        if self._recording.is_set():
            self.status_var.set("Already recording")
            return

        if self._transcribing.is_set():
            self.status_var.set("Wait for the current transcription to finish")
            return

        try:
            self.recorder.start()
        except Exception as exc:
            messagebox.showerror("Microphone Error", str(exc))
            self.status_var.set("Microphone unavailable")
            return

        self._recording.set()
        self._set_transcript_placeholder("Recording in progress. Press End Recording when you are done speaking.")
        self.status_var.set("Recording Urdu audio...")
        self._sync_controls()

    def stop_transcription(self) -> None:
        if not self._recording.is_set():
            return

        self._recording.clear()
        audio_data = self.recorder.stop()
        self._forward_recorder_status()

        if audio_data.size == 0:
            self.status_var.set("No audio captured")
            self._set_transcript_placeholder("No audio was captured. Press Start Recording and try again.")
            self._sync_controls()
            return

        self._transcribing.set()
        self._set_transcript_placeholder("Transcribing Urdu audio. Please wait.")
        self.status_var.set("Transcribing Urdu audio...")
        self._transcription_thread = threading.Thread(target=self._transcribe_recording, args=(audio_data,), daemon=True)
        self._transcription_thread.start()
        self._sync_controls()

    def clear_transcript(self) -> None:
        self._set_transcript_placeholder()

    def _transcribe_recording(self, audio_data: np.ndarray) -> None:
        try:
            audio_bytes = self._to_wav_bytes(audio_data)
            transcript = self.speech_client.transcribe(
                audio_bytes=audio_bytes,
                provider=self.provider_var.get(),
                model=self.model_var.get(),
                language=URDU_LANGUAGE_CODE,
            )
            self.transcript_queue.put(transcript)
            self.ui_status_queue.put("Transcript ready")
        except Exception as exc:
            self.transcript_queue.put("")
            self.ui_status_queue.put(f"Transcription error: {exc}")
        finally:
            self._transcribing.clear()

    def _forward_recorder_status(self) -> None:
        while True:
            try:
                message = self.recorder.status_queue.get_nowait()
            except queue.Empty:
                return
            self.ui_status_queue.put(message)

    def _refresh_ui_from_queues(self) -> None:
        self._forward_recorder_status()

        while True:
            try:
                status_message = self.ui_status_queue.get_nowait()
            except queue.Empty:
                break
            self.status_var.set(status_message)

        while True:
            try:
                transcript = self.transcript_queue.get_nowait()
            except queue.Empty:
                break

            self._display_transcript(transcript)

        self._sync_controls()
        self.root.after(200, self._refresh_ui_from_queues)

    def _sync_controls(self) -> None:
        is_busy = self._recording.is_set() or self._transcribing.is_set()

        if is_busy:
            self.start_button.state(["disabled"])
        else:
            self.start_button.state(["!disabled"])

        if self._recording.is_set():
            self.stop_button.state(["!disabled"])
        else:
            self.stop_button.state(["disabled"])

        combo_state = "disabled" if is_busy else "readonly"
        self.provider_combo.configure(state=combo_state)
        self.model_combo.configure(state=combo_state)

    def _on_close(self) -> None:
        if self._recording.is_set():
            self._recording.clear()
            self.recorder.stop()
        self.root.destroy()

    def _to_wav_bytes(self, audio_chunk: np.ndarray) -> bytes:
        with io.BytesIO() as wav_buffer:
            sf.write(wav_buffer, audio_chunk, self.config.sample_rate, format="WAV")
            return wav_buffer.getvalue()


def main() -> None:
    root = tk.Tk()
    app = LiveTranscriberApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
