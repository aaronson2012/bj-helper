from __future__ import annotations

import sys
from pathlib import Path
import os

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
)

from bj_helper.config import AppConfig, load_config
from bj_helper.control import ControlServer, ControlServerStatus
from bj_helper.debug import debug_log_path, log_debug
from bj_helper.integration import APP_ID, ensure_app_icon, ensure_desktop_entry
from bj_helper.parser import Command, parse_cards_phrase, parse_command_phrase
from bj_helper.speech import AudioCuePlayer, ListeningMode, OfflineSpeechRecognizer, TextSpeaker
from bj_helper.state import BlackjackController, Phase
from bj_helper.strategy import Action, RulesPreset


class AlreadyRunningError(RuntimeError):
    pass


class BjHelperApp:
    def __init__(self, config: AppConfig) -> None:
        ensure_desktop_entry()
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName("bj-helper")
        self.qt_app.setDesktopFileName(APP_ID)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self._icon_path = ensure_app_icon()
        self._configure_icon_theme()
        self._app_icon = self._tray_icon()
        self.qt_app.setWindowIcon(self._app_icon)
        self.config = config
        self.controller = BlackjackController(
            RulesPreset(
                deck_mode=config.rules.deck_mode,
                dealer_soft_17=config.rules.dealer_soft_17,
                double_after_split=config.rules.double_after_split,
                max_split_hands=config.rules.max_split_hands,
                surrender=config.rules.surrender,
                insurance_enabled=config.rules.insurance_enabled,
            )
        )
        self.speaker = TextSpeaker(
            backend=config.tts.backend,
            voice_name=config.tts.voice,
            language=config.tts.language,
            rate=config.tts.rate,
            pitch=config.tts.pitch,
            volume=config.tts.volume,
            model_path=config.tts.model_path,
            speaker_id=config.tts.speaker_id,
        )
        self.recognizer = OfflineSpeechRecognizer(
            model_path=config.stt.model_path,
            sample_rate=config.stt.sample_rate,
            listen_seconds=config.stt.listen_seconds,
        )
        self.cue_player = AudioCuePlayer(
            sound_path=config.recording_cue_path,
            volume=config.recording_cue_volume,
        )
        self.listening = False
        self._speaker_active = False
        self._capture_start_cue_pending = False
        self._capture_end_cue_pending = False
        self._last_title = "Ready"
        self._last_message = self._startup_message()
        self._pending_speech = ""
        self._speech_timer = QTimer(self.qt_app)
        self._speech_timer.setSingleShot(True)
        self._speech_timer.timeout.connect(self._flush_speech)
        self._tray_retry_timer = QTimer(self.qt_app)
        self._tray_retry_timer.setInterval(1500)
        self._tray_retry_timer.timeout.connect(self._ensure_tray_visible)
        self.control_server = ControlServer(self._start_listening_from_control)
        control_status = self.control_server.start()
        if control_status is ControlServerStatus.ALREADY_RUNNING:
            log_debug("app_already_running")
            raise AlreadyRunningError
        if control_status is ControlServerStatus.FAILED:
            raise RuntimeError("Could not initialize the local control server.")
        tray_icon = self._tray_icon()
        self.tray = QSystemTrayIcon(tray_icon, self.qt_app)
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.qt_app.aboutToQuit.connect(self.recognizer.stop_listening)
        self.qt_app.aboutToQuit.connect(self.cue_player.stop)
        self.qt_app.aboutToQuit.connect(self.speaker.stop)
        self.qt_app.aboutToQuit.connect(self.control_server.stop)
        self._connect_signals()
        self._ensure_tray_visible()
        self._publish(self._startup_message(), "Idle", speak=False)
        log_debug(
            "app_started",
            debug_log_path=str(debug_log_path()) if debug_log_path() else "",
            cue_path=config.recording_cue_path,
            cue_volume=config.recording_cue_volume,
            stt_model=config.stt.model_path,
            listen_seconds=config.stt.listen_seconds,
            tts_backend=config.tts.backend,
            tts_model=config.tts.model_path,
            cwd=os.getcwd(),
        )
        if not self.speaker.available:
            self._publish("Text-to-speech is unavailable on this machine.", "TTS Error", speak=False, notify=True)

    def _configure_icon_theme(self) -> None:
        search_paths = [str(Path.home() / ".local" / "share" / "icons"), "/usr/share/icons", *QIcon.themeSearchPaths()]
        deduped_search_paths = list(dict.fromkeys(search_paths))
        QIcon.setThemeSearchPaths(deduped_search_paths)
        if hasattr(QIcon, "setFallbackThemeName"):
            QIcon.setFallbackThemeName("hicolor")

    def _tray_icon(self) -> QIcon:
        tray_icon = QIcon.fromTheme("bj-helper")
        if tray_icon.isNull():
            tray_icon = QIcon(str(self._icon_path))
        return tray_icon

    def _ensure_tray_visible(self) -> None:
        self.tray.setIcon(self._tray_icon())
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            if self.tray.isVisible():
                self._tray_retry_timer.stop()
                log_debug("tray_visible")
                self._refresh_tray_state(self._last_title, self._last_message)
                return
        if not self._tray_retry_timer.isActive():
            log_debug("tray_retry_scheduled")
            self._tray_retry_timer.start()

    def _build_menu(self) -> None:
        self.status_action = QAction("", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.context_action = QAction("", self.menu)
        self.context_action.setEnabled(False)
        self.menu.addAction(self.context_action)

        self.menu.addSeparator()

        listen_action = QAction("Start Listening", self.menu)
        listen_action.triggered.connect(self.start_button_listening)
        self.menu.addAction(listen_action)

        self.repeat_action = QAction("Repeat Last Advice", self.menu)
        self.repeat_action.setEnabled(False)
        self.repeat_action.triggered.connect(self._repeat_last_advice)
        self.menu.addAction(self.repeat_action)

        next_hand_action = QAction("Next Hand", self.menu)
        next_hand_action.triggered.connect(lambda: self._handle_command(Command.NEXT_HAND))
        self.menu.addAction(next_hand_action)

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.qt_app.quit)
        self.menu.addAction(quit_action)

    def _connect_signals(self) -> None:
        self.tray.activated.connect(self._handle_tray_activated)
        self.recognizer.phrase_ready.connect(self._handle_phrase)
        self.recognizer.error.connect(self._handle_recognizer_error)
        self.recognizer.listening_changed.connect(self._handle_listening_state)
        self.speaker.error.connect(self._handle_speaker_error)
        self.speaker.finished.connect(self._handle_speech_finished)

    def start_button_listening(self) -> None:
        log_debug("app_start_listening", source="manual")
        self._begin_active_capture()

    def _start_listening_from_control(self) -> None:
        log_debug("app_start_listening", source="control")
        self._begin_active_capture()

    def _begin_active_capture(self) -> None:
        if self.listening:
            log_debug("app_start_listening_ignored", reason="already_listening")
            return
        log_debug("app_begin_active_capture", phase=self.controller.phase.value, mode=self._listening_mode().value)
        self._capture_start_cue_pending = True
        self._capture_end_cue_pending = True
        self._arm_controller_if_needed()
        self._cancel_speech()
        self._publish(self._listening_prompt(), "Listening", speak=False)
        self.recognizer.start_listening(mode=self._listening_mode())

    def _arm_controller_if_needed(self) -> None:
        if self.controller.phase in {Phase.IDLE, Phase.ROUND_COMPLETE}:
            log_debug("app_arm_controller", prior_phase=self.controller.phase.value)
            reply = self.controller.arm()
            self._publish(reply.spoken, "Listening", speak=False)
        else:
            log_debug("app_controller_already_armed", phase=self.controller.phase.value)
            self._publish("Listening for the next phrase.", "Listening", speak=False)

    def _handle_listening_state(self, listening: bool) -> None:
        self.listening = listening
        log_debug("app_listening_state", listening=listening)
        if listening:
            if self._capture_start_cue_pending:
                self.cue_player.play()
                self._capture_start_cue_pending = False
            self._publish(self._active_listening_status(), "Listening", speak=False)
        else:
            if self._capture_end_cue_pending:
                self.cue_player.play()
                self._capture_end_cue_pending = False
            self._refresh_tray_state("Ready", self._last_message)

    def _handle_phrase(self, text: str) -> None:
        log_debug("app_phrase", text=text, phase=self.controller.phase.value)
        parsed_command = parse_command_phrase(text)
        if parsed_command.command in {Command.NEXT_HAND, Command.CANCEL, Command.UNDO, Command.REPEAT}:
            self._handle_command(parsed_command.command)
            return

        phase = self.controller.phase
        if phase in {Phase.AWAIT_OPENING, Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            expected = 3 if phase == Phase.AWAIT_OPENING else 1
            parsed = parse_cards_phrase(text, expected_count=expected)
            if parsed.error:
                self._publish(parsed.error, "Parse Error")
                return
            reply = self.controller.handle_cards(parsed.cards or [])
            log_debug("app_cards_reply", spoken=reply.spoken, display=reply.display, phase=reply.phase.value)
            self._publish(reply.display or reply.spoken, "Advice", speech_message=reply.spoken)
            return

        if parsed_command.error:
            self._publish(parsed_command.error, "Parse Error")
            return
        self._handle_command(parsed_command.command)

    def _handle_command(self, command: Command | None) -> None:
        if command is None:
            return
        reply = self.controller.handle_command(command)
        should_speak = command is Command.REPEAT
        log_debug("app_command_reply", command=command.value, spoken=reply.spoken, display=reply.display, phase=reply.phase.value)
        self._publish(
            reply.display or reply.spoken,
            "Advice",
            speak=should_speak,
            speech_message=reply.spoken,
        )

    def _handle_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is not QSystemTrayIcon.ActivationReason.Trigger:
            return
        log_debug("tray_activated", reason=reason.name)
        if self.listening:
            return
        self.start_button_listening()

    def _handle_recognizer_error(self, text: str) -> None:
        log_debug("recognizer_error", text=text)
        self._publish(text, "Speech Error", notify=self._should_notify_recognizer_error(text))

    def _handle_speaker_error(self, text: str) -> None:
        self._speaker_active = False
        log_debug("speaker_error", text=text)
        self._publish(text, "TTS Error", speak=False, notify=True)

    def _handle_speech_finished(self) -> None:
        self._speaker_active = False
        log_debug("speaker_finished")

    def _publish(
        self,
        message: str,
        title: str,
        *,
        speak: bool = True,
        notify: bool = False,
        speech_message: str | None = None,
    ) -> None:
        log_debug("publish", title=title, message=message, speak=speak, notify=notify, speech_message=speech_message)
        self._refresh_tray_state(title, message)
        if notify:
            self.tray.showMessage("bj-helper", message, QSystemTrayIcon.MessageIcon.Information, 2500)
        if speak:
            self._queue_speech(speech_message or message)

    def _refresh_tray_state(self, title: str, message: str) -> None:
        self._last_title = title
        self._last_message = message
        context = self._context_line()
        self.tray.setToolTip("Blackjack Helper")
        self.status_action.setText(self._menu_text("State", self._status_badge(title)))
        self.context_action.setText(self._menu_text("Context", context))
        self.repeat_action.setEnabled(bool(self.controller.last_advice) and self.speaker.available)

    def _menu_text(self, label: str, text: str, *, limit: int = 88) -> str:
        single_line = " ".join(text.split())
        if len(single_line) > limit:
            single_line = single_line[: limit - 3] + "..."
        return f"{label}: {single_line}"

    def _status_badge(self, title: str) -> str:
        if title in {"Parse Error", "Speech Error", "TTS Error"}:
            return title
        if self.listening:
            return "Listening"
        phase_labels = {
            Phase.IDLE: "Ready",
            Phase.AWAIT_OPENING: "Opening Hand",
            Phase.AWAIT_CARD: "Waiting For Card",
            Phase.AWAIT_SPLIT_CARD: "Split Hand",
            Phase.ROUND_COMPLETE: "Round Complete",
        }
        return phase_labels.get(self.controller.phase, title)

    def _context_line(self) -> str:
        round_state = self.controller.round_state
        if round_state is None:
            return "Waiting for the opening hand."
        parts = [f"Dealer: {round_state.dealer_upcard.display}"]
        hands: list[str] = []
        for index, hand in enumerate(round_state.hands, start=1):
            label = f"Hand {index}"
            if index - 1 == round_state.active_hand_index and not hand.finished:
                label = f"Active {label}"
            suffix = " complete" if hand.finished else ""
            hands.append(f"{label}: {hand.label()}{suffix}")
        parts.extend(hands)
        return " | ".join(parts)

    def _repeat_last_advice(self) -> None:
        advice = self.controller.last_advice.strip()
        if not advice:
            return
        log_debug("repeat_last_advice", advice=advice)
        self._cancel_speech()
        self._speak(advice)

    def _should_notify_recognizer_error(self, text: str) -> bool:
        normalized = text.strip().lower()
        if not normalized:
            return False
        if normalized == "nothing was recognized.":
            return False
        runtime_prefixes = (
            "configure stt.model_path",
            "ffmpeg is not installed.",
            "could not load vosk model:",
            "speech recognition failed:",
        )
        return normalized.startswith(runtime_prefixes)

    def _speak(self, message: str) -> None:
        if not message or not self.speaker.available:
            return
        self._speaker_active = True
        self.speaker.speak(message)

    def _queue_speech(self, message: str) -> None:
        self._pending_speech = message
        log_debug("queue_speech", message=message)
        self._speech_timer.stop()
        self._speech_timer.start(260)

    def _flush_speech(self) -> None:
        message = self._pending_speech.strip()
        self._pending_speech = ""
        log_debug("flush_speech", message=message)
        if message:
            self._speak(message)

    def _cancel_speech(self) -> None:
        self._pending_speech = ""
        self._speech_timer.stop()
        self._speaker_active = False
        log_debug("cancel_speech")
        self.speaker.stop()

    def _listening_mode(self) -> ListeningMode:
        phase = self.controller.phase
        if phase == Phase.AWAIT_OPENING:
            return ListeningMode.OPENING
        if phase in {Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            return ListeningMode.CARD
        return ListeningMode.GENERIC

    def _listening_prompt(self) -> str:
        return self._expected_phrase()

    def _active_listening_status(self) -> str:
        return f"Listening now. {self._expected_phrase()}"

    def _expected_phrase(self) -> str:
        phase = self.controller.phase
        if phase == Phase.AWAIT_OPENING:
            return "Say dealer card, player card one, and player card two."
        if phase == Phase.AWAIT_CARD:
            if self.controller.pending_action == Action.DOUBLE:
                return "Say the double card."
            return "Say the drawn card."
        if phase == Phase.AWAIT_SPLIT_CARD:
            if self.controller.split_targets:
                return f"Say the replacement card for hand {self.controller.split_targets[0] + 1}."
            return "Say the replacement card."
        if phase == Phase.ROUND_COMPLETE:
            return "Say dealer card, player card one, and player card two."
        return "Say your phrase."

    def _startup_message(self) -> str:
        opening = "Say dealer, player one, and player two."
        return f"Left click the tray icon. {opening}"

    def run(self) -> int:
        return self.qt_app.exec()


def run_app() -> int:
    try:
        return BjHelperApp(load_config()).run()
    except AlreadyRunningError:
        return 0
