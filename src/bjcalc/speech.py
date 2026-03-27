from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import wave
from enum import StrEnum

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtTextToSpeech import QTextToSpeech

from bjcalc.cards import CARD_ALIASES
from bjcalc.parser import COMMAND_ALIASES


class SpeechError(RuntimeError):
    """Speech subsystem error."""


class ListeningMode(StrEnum):
    OPENING = "opening"
    CARD = "card"
    COMMAND = "command"
    GENERIC = "generic"


CARD_GRAMMAR = sorted(set(CARD_ALIASES))
COMMAND_GRAMMAR = sorted(set(COMMAND_ALIASES))


class TextSpeaker(QObject):
    error = pyqtSignal(str)

    def __init__(
        self,
        backend: str = "speechd",
        voice_name: str = "",
        language: str = "en-US",
        rate: float = 0.0,
        pitch: float = 0.0,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._voice_name = voice_name
        self._language = language
        self._rate = int(max(-100, min(100, rate * 100)))
        self._pitch = int(max(-100, min(100, pitch * 100)))
        self._process: subprocess.Popen[str] | None = None
        self._tts: QTextToSpeech | None = None
        self.available = False
        if backend == "speechd" and shutil.which("spd-say"):
            self.available = True
            return
        if backend == "espeak-ng" and shutil.which("espeak-ng"):
            self.available = True
            return
        if not QTextToSpeech.availableEngines():
            return
        self._tts = QTextToSpeech(self)
        self._tts.setRate(rate)
        self._tts.setPitch(pitch)
        if voice_name:
            for voice in self._tts.availableVoices():
                if voice.name() == voice_name:
                    self._tts.setVoice(voice)
                    break
        self.available = self._tts.engine() != ""

    def speak(self, text: str) -> None:
        if not self.available:
            self.error.emit("No text-to-speech backend is available.")
            return
        if self._backend == "speechd" and shutil.which("spd-say"):
            self._stop_process()
            command = [
                "spd-say",
                "-C",
            ]
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            command = [
                "spd-say",
                "-w",
                "-o",
                "rhvoice",
                "-l",
                self._language,
                "-r",
                str(self._rate),
                "-p",
                str(self._pitch),
            ]
            if self._voice_name:
                command.extend(["-y", self._voice_name])
            command.append(text)
            self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            return
        if self._backend == "espeak-ng" and shutil.which("espeak-ng"):
            self._stop_process()
            command = ["espeak-ng", "-v", self._voice_name or "en-us", "-s", "170"]
            command.append(text)
            self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            return
        if self._tts is None:
            self.error.emit("No text-to-speech backend is available.")
            return
        self._tts.stop()
        self._tts.say(text)

    def stop(self) -> None:
        self._stop_process()
        if self._tts is not None:
            self._tts.stop()

    def _stop_process(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
        self._process = None


class OfflineSpeechRecognizer(QObject):
    phrase_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    listening_changed = pyqtSignal(bool)

    def __init__(self, model_path: str, *, sample_rate: int, listen_seconds: float) -> None:
        super().__init__()
        self._model_path = model_path
        self._sample_rate = sample_rate
        self._listen_seconds = listen_seconds
        self._model = None
        self._kaldi_recognizer_type = None
        self._recognizer = None
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_capture)
        self._capture_process: subprocess.Popen[bytes] | None = None
        self._capture_path = ""
        self._push_to_talk = False

    def start_listening(self, *, push_to_talk: bool = False, mode: ListeningMode = ListeningMode.GENERIC) -> None:
        if not self._model_path:
            self.error.emit("Configure stt.model_path before listening.")
            return
        if not shutil.which("ffmpeg"):
            self.error.emit("ffmpeg is not installed.")
            return
        if self._capture_process is not None and self._capture_process.poll() is None:
            return

        try:
            model = self._get_model()
        except Exception as exc:
            self.error.emit(f"Could not load Vosk model: {exc}")
            return

        assert self._kaldi_recognizer_type is not None
        self._recognizer = self._kaldi_recognizer_type(model, self._sample_rate)
        self._recognizer.SetGrammar(json.dumps(self._grammar_for_mode(mode)))
        handle, capture_path = tempfile.mkstemp(prefix="bjcalc-", suffix=".wav")
        os.close(handle)
        self._capture_path = capture_path
        self._push_to_talk = push_to_talk
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "pulse",
            "-i",
            "default",
            "-ac",
            "1",
            "-ar",
            str(self._sample_rate),
            self._capture_path,
        ]
        if not push_to_talk:
            command[-1:-1] = ["-t", str(self._listen_seconds)]
        self._capture_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not push_to_talk:
            self._poll_timer.start(100)
        self.listening_changed.emit(True)

    def stop_listening(self) -> None:
        if self._capture_process is None:
            return
        if self._capture_process.poll() is None:
            self._capture_process.terminate()
        self._poll_timer.stop()
        stderr = b""
        if self._capture_process.stderr is not None:
            stderr = self._capture_process.stderr.read()
        self._capture_process = None
        self._push_to_talk = False
        self.listening_changed.emit(False)
        if stderr:
            self.error.emit(stderr.decode("utf-8", "replace").strip())
            self._cleanup_capture()
            return
        try:
            result = self._transcribe_capture()
        except Exception as exc:
            self._cleanup_capture()
            self.error.emit(f"Speech recognition failed: {exc}")
            return
        self._cleanup_capture()

        text = str(result.get("text", "")).strip()
        if not text:
            self.error.emit("Nothing was recognized.")
            return
        self.phrase_ready.emit(text)

    def _check_capture(self) -> None:
        if self._capture_process is None:
            return
        if self._capture_process.poll() is None:
            return
        self.stop_listening()

    def _transcribe_capture(self) -> dict:
        if self._recognizer is None or not self._capture_path:
            return {}
        with wave.open(self._capture_path, "rb") as handle:
            while True:
                data = handle.readframes(4000)
                if not data:
                    break
                self._recognizer.AcceptWaveform(data)
        final_result = self._recognizer.FinalResult()
        return json.loads(final_result) if final_result else {}

    def _cleanup_capture(self) -> None:
        if self._capture_path and os.path.exists(self._capture_path):
            os.unlink(self._capture_path)
        self._capture_path = ""

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise SpeechError("Vosk is not installed in the active environment.") from exc
        self._model = Model(self._model_path)
        self._kaldi_recognizer_type = KaldiRecognizer
        return self._model

    def _grammar_for_mode(self, mode: ListeningMode) -> list[str]:
        if mode in {ListeningMode.OPENING, ListeningMode.CARD}:
            return CARD_GRAMMAR
        if mode is ListeningMode.COMMAND:
            return COMMAND_GRAMMAR
        return sorted(set(CARD_GRAMMAR + COMMAND_GRAMMAR))
