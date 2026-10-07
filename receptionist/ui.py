"""
ui.py — Modern CustomTkinter GUI for the Urdu Medical Receptionist Agent.

Layout
──────
  ┌─────────────────────────────────────────────────────────────────┐
  │  🏥  [Header: clinic name + agent avatar + status badge]        │
  ├──────────────────────────────┬──────────────────────────────────┤
  │                              │  📋 مریض کی معلومات              │
  │     💬 Conversation          │  Patient Information              │
    │     (chat bubbles,           │  ─────────────────────────────── │
    │      auto-scroll)            │  ✓ / ○  7 field rows             │
  │                              │  Progress bar                    │
  ├──────────────────────────────┴──────────────────────────────────┤
  │  ● Status dot  |  State label  |  Latency strip  |  Tech stack  │
  └─────────────────────────────────────────────────────────────────┘

Threading
─────────
  - Main thread:   Tkinter event loop (all widget updates)
  - Worker thread: ReceptionistAgent.run()  (blocking I/O)
  - Communication: thread-safe queue.Queue polled every 50 ms
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Any

import customtkinter as ctk

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── Palette ───────────────────────────────────────────────────────────────────
C = {
    "bg":           "#EEF0F3",
    "header":       "#FFFFFF",
    "sidebar":      "#061C3A",
    "chat":         "#EEF0F3",
    "agent_bubble": "#FFFFFF",
    "patient_bubble":"#EAF1FB",
    "field_row":    "#FFFFFF",
    "divider":      "#D9DEE7",
    "accent":       "#0A2240",
    "accent2":      "#3F6EA4",
    "avatar_bg":    "#1E88B5",
    "on_avatar":    "#FFFFFF",
    "text":         "#1F2937",
    "text2":        "#6B7280",
    "listening":    "#16A34A",
    "processing":   "#D97706",
    "speaking":     "#2563EB",
    "idle":         "#6B7280",
    "complete":     "#16A34A",
    "error":        "#DC2626",
}

STATUS_MAP: dict[str, tuple[str, str, str]] = {
    "review":     ("Ready to forward / بھیجنے کے لیے تیار", C["idle"], "○"),
    "greeting":   ("Starting conversation…",   C["speaking"],   "◉"),
    "listening":  ("🎤  Listening…  / سنا جا رہا ہے", C["listening"], "◉"),
    "processing": ("⚙️  Processing…  / پروسیسنگ",     C["processing"], "◌"),
    "speaking":   ("🔊  Speaking…  / بول رہی ہیں",    C["speaking"],  "◉"),
    "idle":       ("⏸  Ready",                         C["idle"],      "○"),
    "complete":   ("✅  Session Complete!  / مکمل",    C["complete"],  "◉"),
    "error":      ("❌  Error occurred",               C["error"],     "◉"),
}

FIELDS = [
    ("نام",             "نام",           "Full Name",        "👤"),
    ("عمر",             "عمر",           "Age",              "🎂"),
    ("فون_نمبر",        "فون نمبر",      "Phone",            "📱"),
    ("پہلی_بار",        "پہلی بار",      "First Visit",      "🏥"),
    ("پچھلی_بیماریاں",  "پچھلی بیماریاں","Medical History",  "📜"),
    ("آج_کی_شکایت",     "آج کی شکایت",  "Today's Complaint","🩺"),
    ("شعبہ",             "شعبہ",          "Department",       "🏢"),
    ("ڈاکٹر_کی_ترجیح",  "ڈاکٹر",         "Doctor Preference","🩺"),
    ("ملاقات_کی_قسم",    "ملاقات کی قسم", "Visit Type",       "📋"),
    ("بکنگ_کا_وقت",     "بکنگ وقت",     "Booking Slot",     "📅"),
]


class ReceptionistUI(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()

        self.title("🏥  طبی کلینک رسیپشنسٹ ایجنٹ  |  Medical Clinic Receptionist")
        self.geometry("1150x720")
        self.minsize(950, 600)
        self.configure(fg_color=C["bg"])

        self._q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._field_widgets: dict[str, tuple] = {}
        self._fields_filled: int = 0
        self._turn_count: int = 0

        self._build_header()
        self._build_body()
        self._build_status_bar()
        self._ani_frame = 0

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._start_agent)
        self.after(50,  self._poll_queue)
        self.after(600, self._animate_dot)

    # ═══════════════════════════════════════════════════════════════
    # Layout builders
    # ═══════════════════════════════════════════════════════════════

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=C["header"], corner_radius=0, height=82)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", padx=20, pady=10)

        ctk.CTkLabel(
            left, text="🏥", font=("Segoe UI Emoji", 38)
        ).pack(side="left", padx=(0, 10))

        titles = ctk.CTkFrame(left, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(
            titles, text="طبی کلینک رسیپشنسٹ ایجنٹ",
            font=("Segoe UI", 19, "bold"), text_color=C["accent"]
        ).pack(anchor="w")
        ctk.CTkLabel(
            titles, text="Urdu Medical Receptionist Agent",
            font=("Segoe UI", 10), text_color=C["text2"]
        ).pack(anchor="w")

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side="right", padx=22, pady=10)

        avatar = ctk.CTkFrame(
            right, fg_color=C["avatar_bg"], width=54, height=54, corner_radius=27
        )
        avatar.pack(side="left", padx=(0, 10))
        avatar.pack_propagate(False)
        ctk.CTkLabel(
            avatar, text="ث", font=("Segoe UI", 24, "bold"), text_color=C["on_avatar"]
        ).pack(expand=True)

        info = ctk.CTkFrame(right, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(
            info, text="ثمرہ", font=("Segoe UI", 16, "bold"), text_color=C["accent"]
        ).pack(anchor="w")
        self._badge = ctk.CTkLabel(
            info, text="● Initializing",
            font=("Segoe UI", 10), text_color=C["idle"]
        )
        self._badge.pack(anchor="w")

        ctk.CTkFrame(self, fg_color=C["divider"], height=1, corner_radius=0).pack(fill="x")

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        chat_pane = ctk.CTkFrame(body, fg_color=C["chat"], corner_radius=0)
        chat_pane.pack(side="left", fill="both", expand=True)

        chat_header = ctk.CTkFrame(chat_pane, fg_color="transparent", height=36)
        chat_header.pack(fill="x", padx=16, pady=(10, 0))
        chat_header.pack_propagate(False)
        ctk.CTkLabel(
            chat_header, text="💬  Conversation / گفتگو",
            font=("Segoe UI", 12, "bold"), text_color=C["text2"]
        ).pack(side="left", anchor="w")
        self._turn_label = ctk.CTkLabel(
            chat_header, text="Turn 0",
            font=("Segoe UI", 10), text_color=C["text2"]
        )
        self._turn_label.pack(side="right", anchor="e")

        self._chat_frame = ctk.CTkScrollableFrame(
            chat_pane, fg_color="transparent",
            scrollbar_button_color=C["divider"],
            scrollbar_button_hover_color=C["accent2"],
        )
        self._chat_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        sidebar_shell = ctk.CTkFrame(
            body, fg_color=C["sidebar"], width=310, corner_radius=0
        )
        sidebar_shell.pack(side="right", fill="y")
        sidebar_shell.pack_propagate(False)
        self._build_forward_action(sidebar_shell)
        sidebar = ctk.CTkScrollableFrame(
            sidebar_shell,
            fg_color=C["sidebar"],
            corner_radius=0,
            scrollbar_button_color=C["accent2"],
            scrollbar_button_hover_color=C["avatar_bg"],
        )
        sidebar.pack(fill="both", expand=True)
        self._build_sidebar(sidebar)

    def _build_forward_action(self, parent: ctk.CTkFrame) -> None:
        action = ctk.CTkFrame(
            parent,
            fg_color=C["sidebar"],
            corner_radius=0,
            height=76,
        )
        action.pack(side="bottom", fill="x")
        action.pack_propagate(False)
        ctk.CTkFrame(
            action,
            fg_color="#39506D",
            height=1,
            corner_radius=0,
        ).pack(fill="x")
        self._forward_button = ctk.CTkButton(
            action,
            text="Save & Forward  |  محفوظ کریں",
            command=self._request_forward,
            state="disabled",
            height=42,
            corner_radius=6,
            fg_color=C["accent2"],
            hover_color=C["avatar_bg"],
            text_color_disabled="#8FA3BC",
        )
        self._forward_button.pack(fill="x", padx=12, pady=16)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(
            parent, text="📋  Patient Information",
            font=("Segoe UI", 13, "bold"), text_color="#F8FAFC"
        ).pack(pady=(16, 2), padx=16, anchor="w")
        ctk.CTkLabel(
            parent, text="مریض کی معلومات",
            font=("Segoe UI", 11), text_color="#AFC2DA"
        ).pack(padx=16, anchor="w")

        ctk.CTkFrame(parent, fg_color=C["divider"], height=1).pack(
            fill="x", padx=14, pady=(10, 8)
        )

        ctk.CTkLabel(
            parent,
            text="Available appointments",
            font=("Segoe UI", 11, "bold"),
            text_color="#F8FAFC",
        ).pack(padx=16, anchor="w")
        self._schedule_doctor = ctk.CTkLabel(
            parent,
            text="Loading Dr. Shaimaan's schedule...",
            font=("Segoe UI", 9),
            text_color="#AFC2DA",
        )
        self._schedule_doctor.pack(padx=16, pady=(1, 5), anchor="w")
        self._schedule_frame = ctk.CTkFrame(
            parent,
            fg_color="transparent",
            corner_radius=0,
        )
        self._schedule_frame.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkFrame(parent, fg_color=C["divider"], height=1).pack(
            fill="x", padx=14, pady=(2, 8)
        )

        for json_key, urdu_lbl, eng_lbl, icon in FIELDS:
            card = ctk.CTkFrame(parent, fg_color=C["field_row"], corner_radius=8)
            card.pack(fill="x", padx=12, pady=3)

            dot = ctk.CTkLabel(
                card, text="○", font=("Segoe UI", 15),
                text_color=C["idle"], width=26
            )
            dot.pack(side="left", padx=(10, 2), pady=8)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(side="left", fill="x", expand=True, padx=4, pady=6)

            top_row = ctk.CTkFrame(inner, fg_color="transparent")
            top_row.pack(fill="x")
            ctk.CTkLabel(
                top_row, text=f"{icon}  {urdu_lbl}",
                font=("Segoe UI", 11, "bold"), text_color=C["text"]
            ).pack(side="left")
            ctk.CTkLabel(
                top_row, text=f"  {eng_lbl}",
                font=("Segoe UI", 9), text_color=C["text2"]
            ).pack(side="left")

            val = ctk.CTkLabel(
                inner, text="—", font=("Segoe UI", 10),
                text_color=C["text2"], wraplength=210, justify="left"
            )
            val.pack(anchor="w")

            self._field_widgets[json_key] = (dot, val)

        ctk.CTkFrame(parent, fg_color=C["divider"], height=1).pack(
            fill="x", padx=14, pady=(12, 6)
        )
        ctk.CTkLabel(
            parent, text="Progress", font=("Segoe UI", 10), text_color=C["text2"]
        ).pack(padx=16, anchor="w")

        self._progress_bar = ctk.CTkProgressBar(
            parent, fg_color=C["divider"], progress_color=C["accent"],
            height=8, corner_radius=4
        )
        self._progress_bar.pack(fill="x", padx=16, pady=(4, 2))
        self._progress_bar.set(0)

        self._progress_lbl = ctk.CTkLabel(
            parent, text=f"0 / {len(FIELDS)} fields collected",
            font=("Segoe UI", 9), text_color=C["text2"]
        )
        self._progress_lbl.pack(padx=16, anchor="w")

        ctk.CTkFrame(parent, fg_color=C["divider"], height=1).pack(
            fill="x", padx=14, pady=(14, 6)
        )
        for line in ("STT: Groq Whisper large-v3",
                     "LLM: LLaMA 3.3-70B",
                     "TTS: Edge TTS ur-PK-UzmaNeural"):
            ctk.CTkLabel(
                parent, text=line, font=("Segoe UI", 8), text_color="#AFC2DA"
            ).pack(padx=16, anchor="w")

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="#FFFFFF", height=38, corner_radius=0)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        ctk.CTkFrame(bar, fg_color=C["divider"], height=1, corner_radius=0).pack(fill="x", side="top")

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=16, pady=8)

        self._status_dot = ctk.CTkLabel(
            left, text="○", font=("Segoe UI", 16), text_color=C["idle"]
        )
        self._status_dot.pack(side="left", padx=(0, 6))

        self._status_lbl = ctk.CTkLabel(
            left, text="Initializing…",
            font=("Segoe UI", 11), text_color=C["text2"]
        )
        self._status_lbl.pack(side="left")

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=16)
        ctk.CTkLabel(
            right,
            text="Groq Whisper v3  •  LLaMA 3.3-70B  •  Edge TTS (ur-PK-UzmaNeural)",
            font=("Segoe UI", 8), text_color=C["text2"]
        ).pack()

    # ═══════════════════════════════════════════════════════════════
    # Chat bubble rendering
    # ═══════════════════════════════════════════════════════════════

    def _add_bubble(self, text: str, role: str) -> None:
        is_agent = (role == "agent")
        if role == "patient":
            self._turn_count += 1
            self._turn_label.configure(text=f"Turn {self._turn_count}")

        outer = ctk.CTkFrame(self._chat_frame, fg_color="transparent")
        outer.pack(fill="x", pady=5, padx=4)

        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(side="left" if is_agent else "right")

        if is_agent:
            self._make_avatar(row, "ث", C["on_avatar"], C["accent"], side="left")

        bubble_color = C["agent_bubble"] if is_agent else C["patient_bubble"]
        bubble = ctk.CTkFrame(row, fg_color=bubble_color, corner_radius=14)
        bubble.pack(side="left", padx=4)

        if not is_agent:
            self._make_avatar(row, "م", "#4B5563", "#DCE4EF", side="right")

        name_text = "ثمرہ" if is_agent else "مریض"
        name_color = C["accent"] if is_agent else C["text2"]
        ctk.CTkLabel(
            bubble, text=name_text,
            font=("Segoe UI", 9, "bold"), text_color=name_color
        ).pack(anchor="w", padx=14, pady=(9, 1))

        ctk.CTkLabel(
            bubble, text=text,
            font=("Segoe UI", 12), text_color=C["text"],
            wraplength=480, justify="right"
        ).pack(anchor="e", padx=14, pady=(0, 9))

        ts = datetime.now().strftime("%H:%M")
        ctk.CTkLabel(
            outer, text=ts, font=("Segoe UI", 8), text_color="#1E293B"
        ).pack(side="left" if is_agent else "right", padx=52)

        self.after(60, self._scroll_bottom)

    @staticmethod
    def _make_avatar(
        parent: ctk.CTkFrame, letter: str,
        text_color: str, bg: str, side: str
    ) -> None:
        av = ctk.CTkFrame(parent, fg_color=bg, width=36, height=36, corner_radius=18)
        av.pack(side=side, anchor="n", padx=3, pady=2)
        av.pack_propagate(False)
        ctk.CTkLabel(
            av, text=letter, font=("Segoe UI", 14, "bold"), text_color=text_color
        ).pack(expand=True)

    def _scroll_bottom(self) -> None:
        try:
            self._chat_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # Status bar updates
    # ═══════════════════════════════════════════════════════════════

    def _set_status(self, state: str) -> None:
        label, color, dot = STATUS_MAP.get(
            state, ("Ready", C["idle"], "○")
        )
        self._status_lbl.configure(text=label, text_color=color)
        self._status_dot.configure(text=dot, text_color=color)
        self._badge.configure(
            text=f"● {state.capitalize()}", text_color=color
        )

    def _animate_dot(self) -> None:
        if self._stop.is_set():
            return
        frames = ["◉", "○", "◌", "○"]
        current = self._status_lbl.cget("text")
        if "Listening" in current:
            self._ani_frame = (self._ani_frame + 1) % len(frames)
            self._status_dot.configure(text=frames[self._ani_frame])
        self.after(400, self._animate_dot)

    # ═══════════════════════════════════════════════════════════════
    # Patient info panel
    # ═══════════════════════════════════════════════════════════════

    def _update_patient_info(self, data: dict) -> None:
        filled = 0
        for json_key, urdu_lbl, eng_lbl, _icon in FIELDS:
            value = data.get(json_key, "").strip()
            if json_key not in self._field_widgets:
                continue

            dot, val = self._field_widgets[json_key]
            if value:
                dot.configure(text="✓", text_color=C["complete"])
                val.configure(text=value, text_color=C["text"])
                filled += 1
            else:
                dot.configure(text="○", text_color=C["idle"])
                val.configure(text="—", text_color=C["text2"])

        self._fields_filled = filled
        self._progress_bar.set(filled / len(FIELDS))
        self._progress_lbl.configure(text=f"{filled} / {len(FIELDS)} fields collected")

    def _update_schedule(self, payload: dict) -> None:
        doctor_name = str(payload.get("doctor_name") or "Dr. Shaimaan")
        self._schedule_doctor.configure(
            text=f"{doctor_name} | General Medicine"
        )
        for widget in self._schedule_frame.winfo_children():
            widget.destroy()
        slots = payload.get("slots") or []
        if not slots:
            ctk.CTkLabel(
                self._schedule_frame,
                text="No slots available",
                font=("Segoe UI", 9),
                text_color="#AFC2DA",
            ).pack(anchor="w", padx=4, pady=3)
            return
        for index, slot in enumerate(slots, start=1):
            ctk.CTkLabel(
                self._schedule_frame,
                text=f"{index}. {slot.get('label') or slot.get('start_at') or ''}",
                font=("Segoe UI", 9),
                text_color=C["text"],
                fg_color=C["field_row"],
                corner_radius=6,
                anchor="w",
                justify="left",
                wraplength=250,
            ).pack(fill="x", pady=2, ipady=5, padx=1)

    def _set_summary_ready(self, ready: bool | dict) -> None:
        self._summary_revision = ready.get("revision") if isinstance(ready, dict) else None
        ready = bool(ready.get("ready")) if isinstance(ready, dict) else ready
        if ready:
            self._forward_button.configure(
                state="normal",
                text="Save & Forward  |  محفوظ کریں",
            )
        else:
            self._forward_button.configure(
                state="disabled",
                text="Save & Forward  |  محفوظ کریں",
            )

    def _request_forward(self) -> None:
        agent = getattr(self, "_agent", None)
        if agent is None or not agent.request_forward(getattr(self, "_summary_revision", None)):
            return
        self._forward_button.configure(
            state="disabled",
            text="Forwarding…  |  بھیجا جا رہا ہے",
        )
        self._set_status("processing")

    # ═══════════════════════════════════════════════════════════════
    # Agent thread + queue
    # ═══════════════════════════════════════════════════════════════

    def _start_agent(self) -> None:
        from .agent import ReceptionistAgent


        q = self._q

        def cb(event: str):
            def _wrapper(payload=None):
                q.put((event, payload))
            return _wrapper

        callbacks = {
            "agent_msg":    cb("agent_msg"),
            "patient_msg":  cb("patient_msg"),
            "status":       cb("status"),
            "patient_data": cb("patient_data"),
            "summary_ready": cb("summary_ready"),
            "schedule_options": cb("schedule_options"),
        }

        # Run both construction (model loading) AND agent.run() in the
        # background thread so the Tkinter main thread is never blocked.
        def _run() -> None:
            try:
                q.put(("status", "processing"))  # show "loading" in UI
                self._agent = ReceptionistAgent(callbacks=callbacks)
                self._agent.run()
            except Exception as exc:
                q.put(("status", "error"))
                q.put(("agent_msg", f"خرابی پیش آئی: {exc}\n\nError: {exc}"))
                import traceback
                traceback.print_exc()

        self._worker = threading.Thread(
            target=_run, daemon=True, name="agent-worker"
        )
        self._worker.start()

    def _poll_queue(self) -> None:
        """Drain the event queue every 50 ms on the main thread."""
        try:
            while True:
                event, payload = self._q.get_nowait()
                if event == "agent_msg" and payload:
                    self._add_bubble(payload, "agent")
                elif event == "patient_msg" and payload:
                    self._add_bubble(payload, "patient")
                elif event == "status" and payload:
                    self._set_status(payload)
                elif event == "patient_data" and payload is not None:
                    self._update_patient_info(payload)
                elif event == "summary_ready":
                    self._set_summary_ready(payload)
                elif event == "schedule_options" and payload:
                    self._update_schedule(payload)
        except queue.Empty:
            pass

        if not self._stop.is_set():
            self.after(50, self._poll_queue)

    # ═══════════════════════════════════════════════════════════════
    # Window lifecycle
    # ═══════════════════════════════════════════════════════════════

    def _on_close(self) -> None:
        self._stop.set()
        self.destroy()


def launch_ui() -> None:
    app = ReceptionistUI()
    app.mainloop()
