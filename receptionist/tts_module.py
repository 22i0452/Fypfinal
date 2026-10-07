"""
tts_module.py - Text-to-Speech.
Primary  : Cloud multilingual v2  (natural Urdu, optional cloud API key)
Fallback : Microsoft Edge TTS ur-PK-UzmaNeural (used when no key is set)
"""
from __future__ import annotations
import asyncio
import os
import re
import tempfile
import time

import pygame

from config import HF_TTS_API_KEY, HF_TTS_VOICE_ID

# Edge TTS fallback settings
_EDGE_VOICE = "ur-PK-UzmaNeural"
_EDGE_RATE  = "-8%"
_EDGE_PITCH = "-3Hz"
_EDGE_MAX_CHARS = 220
_EDGE_SYNTHESIS_TIMEOUT_SECONDS = 20.0
_PLAYBACK_TIMEOUT_SECONDS = 90.0


class TTSEngine:
    """Synthesises Urdu text and plays through the default speaker."""
    def __init__(self) -> None:
        pygame.mixer.pre_init(frequency=44_100, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        if HF_TTS_API_KEY and HF_TTS_API_KEY != "your_hf_tts_key_here":
            from elevenlabs.client import ElevenLabs as CloudVoiceClient
            self._cloud_tts = CloudVoiceClient(api_key=HF_TTS_API_KEY)
            self._voice_id = HF_TTS_VOICE_ID or self._pick_voice()
            self._backend = "cloud_tts"
            print(f"OK  TTS Engine ready  (Cloud multilingual v2 - voice: {self._voice_id})")
        else:
            self._cloud_tts = None
            self._backend = "edge_tts"
            print("OK  TTS Engine ready  (Edge TTS ur-PK-UzmaNeural - set HF_TTS_API_KEY for better quality)")
    def _pick_voice(self) -> str:
        """Return the first available female voice, or a known default."""
        try:
            voices = self._cloud_tts.voices.get_all().voices
            female = [v for v in voices if getattr(v, "labels", {}).get("gender") == "female"]
            chosen = female[0] if female else voices[0]
            return chosen.voice_id
        except Exception:
            return "21m00Tcm4TlvDq8ikWAM"
    def speak(self, text: str) -> None:
        """Synthesise text and play it (blocking until done)."""
        text = self._normalize_speech_text(text)
        if not text:
            return
        if self._backend == "cloud_tts":
            self._speak_cloud_tts(text)
        else:
            self._speak_edge_tts(text)

    @staticmethod
    def _normalize_speech_text(text: str) -> str:
        clean = (text or "").strip()
        if re.search(r"[\u0600-\u06ff]", clean):
            clean = re.sub(r"(?i)\bdr\s*\.?\s*shaimaan\b", "ڈاکٹر شیمان", clean)
        return re.sub(r"(?i)\bdr\s*\.\s*", "Doctor ", clean)
    def _speak_cloud_tts(self, text: str) -> None:
        try:
            audio_gen = self._cloud_tts.text_to_speech.convert(
                voice_id=self._voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            audio_bytes = b"".join(audio_gen)
            self._play_mp3_bytes(audio_bytes)
        except Exception as exc:
            print(f"WARNING  Cloud TTS error: {exc} - falling back to Edge TTS")
            self._speak_edge_tts(text)

    @staticmethod
    def _speech_chunks(text: str, max_chars: int = _EDGE_MAX_CHARS) -> list[str]:
        """Split long structured replies without breaking words."""
        units: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = " ".join(raw_line.split())
            while len(line) > max_chars:
                boundary = line.rfind(" ", 0, max_chars + 1)
                if boundary < max_chars // 2:
                    boundary = max_chars
                units.append(line[:boundary].strip())
                line = line[boundary:].strip()
            if line:
                units.append(line)

        chunks: list[str] = []
        current = ""
        for unit in units:
            candidate = f"{current}\n{unit}" if current else unit
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = unit
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _speak_edge_tts(self, text: str) -> bool:
        for chunk in self._speech_chunks(text):
            if not self._speak_edge_chunk(chunk):
                return False
        return True

    def _speak_edge_chunk(self, text: str) -> bool:
        import edge_tts

        async def _synth(path: str) -> None:
            voice = _EDGE_VOICE if re.search(r"[\u0600-\u06ff]", text) else "en-US-JennyNeural"
            comm = edge_tts.Communicate(text, voice, rate=_EDGE_RATE, pitch=_EDGE_PITCH)
            await asyncio.wait_for(
                comm.save(path),
                timeout=_EDGE_SYNTHESIS_TIMEOUT_SECONDS,
            )

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(tmp_fd)
        try:
            asyncio.run(_synth(tmp_path))
            if os.path.getsize(tmp_path) <= 0:
                raise RuntimeError("Edge TTS returned empty audio")
            self._play_mp3_file(tmp_path)
            return True
        except TimeoutError:
            print("WARNING  Edge TTS synthesis timed out; speech was skipped safely")
            return False
        except Exception as exc:
            print(f"WARNING  Edge TTS error: {exc}")
            return False
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _unload_music() -> None:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

    def _play_mp3_file(self, path: str) -> None:
        started_at = time.monotonic()
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if time.monotonic() - started_at > _PLAYBACK_TIMEOUT_SECONDS:
                    pygame.mixer.music.stop()
                    raise TimeoutError("TTS playback timed out")
                pygame.time.wait(30)
        finally:
            self._unload_music()

    def _play_mp3_bytes(self, data: bytes) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(tmp_fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            if not data:
                raise RuntimeError("TTS provider returned empty audio")
            self._play_mp3_file(tmp_path)
        except TimeoutError:
            print("WARNING  TTS playback timed out; speech was stopped safely")
        except Exception as exc:
            print(f"WARNING  Playback error: {exc}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    def __del__(self) -> None:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
