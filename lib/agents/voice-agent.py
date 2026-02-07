"""Voice agent utilities for MERID.

This module previously mixed Python and Node.js syntax, which broke static
analysis.  The implementation below keeps the functionality testable while
degrading gracefully when optional audio/ML dependencies are not installed.
"""

from __future__ import annotations

import json
import sys
from typing import Optional

try:  # Optional heavy deps
    import sounddevice as sd  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    sd = None  # type: ignore
    np = None  # type: ignore

try:
    from faster_whisper import WhisperModel  # type: ignore
except ImportError:  # pragma: no cover
    WhisperModel = None  # type: ignore

try:
    from piper.voice import PiperVoice  # type: ignore
except ImportError:  # pragma: no cover
    PiperVoice = None  # type: ignore


class VoiceAgent:
    """Simple STT/TTS helper with dependency guards."""

    def __init__(self, stt_model: str = "base", voice: str = "en_US-lessac-medium.onnx") -> None:
        self._stt = None
        self._tts = None

        if WhisperModel:
            self._stt = WhisperModel(stt_model, device="cpu", compute_type="int8")
        if PiperVoice:
            self._tts = PiperVoice.load(voice)

    def _ensure_audio_stack(self) -> None:
        if sd is None or np is None:
            raise RuntimeError("Audio stack not available (sounddevice/numpy missing)")

    def record(self, duration: int = 5, fs: int = 16_000):
        """Record audio; raises if dependencies are missing."""
        self._ensure_audio_stack()
        recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="float32")  # type: ignore[attr-defined]
        sd.wait()  # type: ignore[attr-defined]
        return np.squeeze(recording)  # type: ignore[attr-defined]

    def speech_to_text(self, audio) -> str:
        if not self._stt:
            raise RuntimeError("WhisperModel not available")
        segments, _ = self._stt.transcribe(audio, language="en")
        return " ".join(seg.text for seg in segments).strip()

    def text_to_speech(self, text: str) -> None:
        self._ensure_audio_stack()
        if not self._tts:
            raise RuntimeError("PiperVoice not available")
        audio = self._tts.synthesize(text)
        sd.play(audio, samplerate=22_050)  # type: ignore[attr-defined]
        sd.wait()  # type: ignore[attr-defined]


def run_cli(command: Optional[str]) -> None:
    """Small CLI used by coverage/integration tests."""
    agent = VoiceAgent()
    if command:
        print(json.dumps({"response": f"Spoke: {command} (simulation)"}))
        return

    # In test environments we avoid entering an infinite loop.
    print(json.dumps({"status": "idle", "message": "Voice agent CLI requires a command argument"}))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        run_cli(arg)
    except Exception as exc:  # pragma: no cover - CLI only
        print(json.dumps({"error": str(exc)}))
