from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from enum import StrEnum

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtTextToSpeech import QTextToSpeech

from bj_helper.cards import CARD_ALIASES
from bj_helper.debug import log_debug
from bj_helper.parser import COMMAND_ALIASES


class SpeechError(RuntimeError):
    """Speech subsystem error."""


class ListeningMode(StrEnum):
    OPENING = "opening"
    CARD = "card"
    GENERIC = "generic"


CARD_GRAMMAR = sorted(token for token in set(CARD_ALIASES) if not token.isdigit())
CONTROL_GRAMMAR = sorted(set(COMMAND_ALIASES))
INVALID_CARD_TOKENS = [
    "zero",
    "oh",
    "o",
    "one",
    "won",
    "eleven",
    "twelve",
    "thirteen",
]


class AudioCuePlayer(QObject):
    def __init__(self, sound_path: str = "", volume: float = 0.18) -> None:
        super().__init__()
        self._sound_path = sound_path
        self._volume = max(0.0, min(3.0, volume))
        self._process: subprocess.Popen[str] | None = None

    @property
    def available(self) -> bool:
        return bool(self._sound_path) and os.path.exists(self._sound_path) and self._playback_command() is not None

    def play(self) -> None:
        command = self._playback_command()
        if command is None:
            log_debug("cue_play_skipped", reason="no_command", sound_path=self._sound_path)
            return
        self.stop()
        log_debug("cue_play", command=command, sound_path=self._sound_path, volume=self._volume)
        self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            log_debug("cue_stop", pid=self._process.pid)
        self._process = None

    def _playback_command(self) -> list[str] | None:
        if not self._sound_path or not os.path.exists(self._sound_path):
            return None
        if self._sound_path.lower().endswith(".wav") and shutil.which("paplay"):
            pulse_volume = str(max(0, min(196608, int(self._volume * 65536))))
            return ["paplay", "--volume", pulse_volume, self._sound_path]
        if self._sound_path.lower().endswith(".wav") and shutil.which("aplay"):
            return ["aplay", self._sound_path]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-af", f"volume={self._volume}", self._sound_path]
        return None


class TextSpeaker(QObject):
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        backend: str = "speechd",
        voice_name: str = "",
        language: str = "en-US",
        rate: float = 0.0,
        pitch: float = 0.0,
        volume: float = 1.0,
        model_path: str = "",
        speaker_id: int | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._voice_name = voice_name
        self._language = language
        self._model_path = model_path
        self._speaker_id = speaker_id
        self._rate = int(max(-100, min(100, rate * 100)))
        self._pitch = int(max(-100, min(100, pitch * 100)))
        self._volume = max(0.0, min(3.0, volume))
        self._process: subprocess.Popen[str] | None = None
        self._playback_path = ""
        self._tts: QTextToSpeech | None = None
        self._qt_speaking = False
        self._resolved_backend = ""
        self.available = False
        if self._can_use_piper():
            self._resolved_backend = "piper"
            self.available = True
            log_debug("tts_backend_ready", backend=self._resolved_backend, model_path=self._model_path)
            return
        if shutil.which("spd-say") and backend in {"speechd", "piper"}:
            self._resolved_backend = "speechd"
            self.available = True
            log_debug("tts_backend_ready", backend=self._resolved_backend)
            return
        if shutil.which("espeak-ng") and backend in {"espeak-ng", "piper", "speechd"}:
            self._resolved_backend = "espeak-ng"
            self.available = True
            log_debug("tts_backend_ready", backend=self._resolved_backend)
            return
        if not QTextToSpeech.availableEngines():
            log_debug("tts_backend_unavailable", reason="no_engines")
            return
        self._tts = QTextToSpeech(self)
        self._tts.stateChanged.connect(self._handle_tts_state)
        self._tts.setRate(rate)
        self._tts.setPitch(pitch)
        if voice_name:
            for voice in self._tts.availableVoices():
                if voice.name() == voice_name:
                    self._tts.setVoice(voice)
                    break
        self._resolved_backend = "qt"
        self.available = self._tts.engine() != ""
        log_debug("tts_backend_ready", backend=self._resolved_backend, available=self.available)

    def speak(self, text: str) -> None:
        if not self.available:
            log_debug("tts_speak_skipped", reason="unavailable", text=text)
            self.error.emit("No text-to-speech backend is available.")
            return
        log_debug("tts_speak", backend=self._resolved_backend, text=text)
        if self._resolved_backend == "piper":
            self._speak_with_piper(text)
            return
        if self._resolved_backend == "speechd" and shutil.which("spd-say"):
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
            self._start_process(command)
            return
        if self._resolved_backend == "espeak-ng" and shutil.which("espeak-ng"):
            command = ["espeak-ng", "-v", self._voice_name or "en-us", "-s", "170"]
            command.append(text)
            self._start_process(command)
            return
        if self._tts is None:
            self.error.emit("No text-to-speech backend is available.")
            return
        self._stop_process()
        self._tts.stop()
        self._tts.say(text)

    def stop(self) -> None:
        log_debug("tts_stop")
        self._stop_process()
        if self._tts is not None:
            self._tts.stop()

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            log_debug("tts_process_terminated", pid=process.pid)
        self._cleanup_playback_path()
        if process is not None or self._qt_speaking:
            self._qt_speaking = False
            self.finished.emit()

    def _start_process(self, command: list[str], *, stop_existing: bool = True) -> None:
        if stop_existing:
            self._stop_process()
        self._process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        log_debug("tts_process_started", pid=self._process.pid, command=command)
        threading.Thread(
            target=self._wait_for_process,
            args=(self._process, self._playback_path),
            daemon=True,
        ).start()

    def _can_use_piper(self) -> bool:
        return (
            self._backend == "piper"
            and bool(self._model_path)
            and self._piper_executable() is not None
            and self._playback_command("/tmp/placeholder.wav") is not None
        )

    def _speak_with_piper(self, text: str) -> None:
        self._stop_process()
        handle, output_path = tempfile.mkstemp(prefix="bj-helper-tts-", suffix=".wav")
        os.close(handle)
        executable = self._piper_executable()
        if executable is None:
            self._cleanup_playback_path(output_path)
            self.error.emit("Piper is not installed.")
            return
        command = [executable, "--model", self._model_path, "--output_file", output_path]
        if self._speaker_id is not None:
            command.extend(["--speaker", str(self._speaker_id)])
        try:
            result = subprocess.run(
                command,
                input=text,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            self._cleanup_playback_path(output_path)
            log_debug("tts_piper_failed", error=str(exc))
            self.error.emit(f"Piper synthesis failed: {exc}")
            return
        if result.returncode != 0:
            self._cleanup_playback_path(output_path)
            detail = result.stderr.strip() or "unknown error"
            log_debug("tts_piper_failed", error=detail)
            self.error.emit(f"Piper synthesis failed: {detail}")
            return
        playback_command = self._playback_command(output_path)
        if playback_command is None:
            self._cleanup_playback_path(output_path)
            log_debug("tts_piper_failed", error="no_playback_command")
            self.error.emit("No audio player is available for Piper output.")
            return
        self._playback_path = output_path
        log_debug("tts_piper_synthesized", output_path=output_path, playback_command=playback_command)
        self._start_process(playback_command, stop_existing=False)

    def _playback_command(self, output_path: str) -> list[str] | None:
        if shutil.which("paplay"):
            pulse_volume = str(max(0, min(196608, int(self._volume * 65536))))
            return ["paplay", "--volume", pulse_volume, output_path]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-af", f"volume={self._volume}", output_path]
        if shutil.which("aplay"):
            return ["aplay", output_path]
        return None

    def _piper_executable(self) -> str | None:
        return shutil.which("piper") or shutil.which("piper-tts")

    def _wait_for_process(self, process: subprocess.Popen[str], output_path: str) -> None:
        return_code = process.wait()
        log_debug("tts_process_exited", pid=process.pid, return_code=return_code)
        if self._process is process:
            self._process = None
            self.finished.emit()
        self._cleanup_playback_path(output_path)

    def _cleanup_playback_path(self, output_path: str | None = None) -> None:
        path = output_path or self._playback_path
        if path and os.path.exists(path):
            os.unlink(path)
        if not output_path or output_path == self._playback_path:
            self._playback_path = ""

    def _handle_tts_state(self, state: QTextToSpeech.State) -> None:
        if state == QTextToSpeech.State.Ready:
            if self._qt_speaking:
                self._qt_speaking = False
                self.finished.emit()
            return
        self._qt_speaking = True


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
        self._mode = ListeningMode.GENERIC

    def start_listening(
        self,
        *,
        mode: ListeningMode = ListeningMode.GENERIC,
    ) -> None:
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
        grammar = self._grammar_for_mode(mode)
        self._recognizer.SetGrammar(json.dumps(grammar))
        self._mode = mode
        log_debug(
            "stt_start",
            mode=mode.value,
            model_path=self._model_path,
            listen_seconds=self._listen_seconds,
            sample_rate=self._sample_rate,
            grammar=grammar,
        )
        handle, capture_path = tempfile.mkstemp(prefix="bj-helper-", suffix=".wav")
        os.close(handle)
        self._capture_path = capture_path
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
            "-t",
            str(self._listen_seconds),
            self._capture_path,
        ]
        self._capture_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        log_debug("stt_capture_started", pid=self._capture_process.pid, command=command, capture_path=self._capture_path)
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
        log_debug("stt_stop", mode=self._mode.value)
        self.listening_changed.emit(False)
        if stderr:
            log_debug("stt_capture_stderr", stderr=stderr.decode("utf-8", "replace").strip())
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
        log_debug("stt_result", mode=self._mode.value, text=text)
        if not text:
            self.error.emit("Nothing was recognized.")
            return
        self.phrase_ready.emit(text)

    def _check_capture(self) -> None:
        if self._capture_process is None:
            return
        if self._capture_process.poll() is None:
            return
        log_debug("stt_capture_completed", pid=self._capture_process.pid)
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
            log_debug("stt_cleanup_capture", capture_path=self._capture_path)
            os.unlink(self._capture_path)
        self._capture_path = ""

    def _get_model(self):
        if self._model is not None:
            log_debug("stt_model_cached", model_path=self._model_path)
            return self._model
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as exc:
            raise SpeechError("Vosk is not installed in the active environment.") from exc
        SetLogLevel(-1)
        self._model = Model(self._model_path)
        self._kaldi_recognizer_type = KaldiRecognizer
        log_debug("stt_model_loaded", model_path=self._model_path)
        return self._model

    def _grammar_for_mode(self, mode: ListeningMode) -> list[str]:
        if mode in {ListeningMode.OPENING, ListeningMode.CARD}:
            return sorted(set(CARD_GRAMMAR + INVALID_CARD_TOKENS + CONTROL_GRAMMAR))
        return sorted(set(CARD_GRAMMAR + INVALID_CARD_TOKENS + CONTROL_GRAMMAR))
