from __future__ import annotations

import sys

from PyQt6.QtCore import QPoint, QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from bjcalc.config import AppConfig, load_config
from bjcalc.integration import APP_ID, ensure_desktop_entry
from bjcalc.parser import Command, parse_cards_phrase, parse_command_phrase
from bjcalc.shortcut import GlobalShortcutManager
from bjcalc.speech import ListeningMode, OfflineSpeechRecognizer, TextSpeaker
from bjcalc.state import BlackjackController, Phase
from bjcalc.strategy import Action, RulesPreset


class HudWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Blackjack Helper")
        self.setStyleSheet(
            """
            QWidget {
              background: #0d1419;
              color: #f4efe7;
              border: 1px solid #24323c;
              border-radius: 14px;
            }
            QLabel#status {
              font-size: 11px;
              font-weight: 700;
              color: #8cc7f2;
              background: #162833;
              border: 1px solid #284252;
              border-radius: 999px;
              padding: 4px 10px;
            }
            QLabel#message {
              font-size: 20px;
              font-weight: 700;
              color: #f7f2ea;
            }
            QLabel#context {
              font-size: 13px;
              color: #c9d4db;
            }
            QLabel#transcript {
              font-size: 12px;
              color: #d0a95a;
            }
            QLabel#footer {
              font-size: 11px;
              color: #7f95a3;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.status = QLabel("Idle", self)
        self.status.setObjectName("status")
        self.message = QLabel("Hold the shortcut to start.", self)
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        self.context = QLabel("No active hand.", self)
        self.context.setObjectName("context")
        self.context.setWordWrap(True)
        self.transcript = QLabel("Heard: waiting", self)
        self.transcript.setObjectName("transcript")
        self.transcript.setWordWrap(True)
        self.footer = QLabel("Push to talk: hold the shortcut, release to submit.", self)
        self.footer.setObjectName("footer")
        self.footer.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.message)
        layout.addWidget(self.context)
        layout.addWidget(self.transcript)
        layout.addWidget(self.footer)
        self.resize(460, 220)

    def render(
        self,
        *,
        status: str,
        message: str,
        context: str,
        transcript: str,
        footer: str,
    ) -> None:
        self.status.setText(status)
        self.message.setText(message)
        self.context.setText(context)
        self.transcript.setText(transcript)
        self.footer.setText(footer)
        if not self.isVisible():
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geometry = screen.availableGeometry()
                self.move(QPoint(geometry.right() - self.width() - 60, geometry.top() + 60))
            self.show()
            self.raise_()


class BjCalcApp:
    def __init__(self, config: AppConfig) -> None:
        ensure_desktop_entry()
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName("Blackjack Helper")
        self.qt_app.setDesktopFileName(APP_ID)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.config = config
        self.controller = BlackjackController(
            RulesPreset(
                deck_mode=config.rules.deck_mode,
                dealer_soft_17=config.rules.dealer_soft_17,
                double_after_split=config.rules.double_after_split,
                surrender=config.rules.surrender,
                insurance_enabled=config.rules.insurance_enabled,
                peek_for_blackjack=config.rules.peek_for_blackjack,
            )
        )
        self.hud = HudWidget()
        self.speaker = TextSpeaker(
            backend=config.tts.backend,
            voice_name=config.tts.voice,
            language=config.tts.language,
            rate=config.tts.rate,
            pitch=config.tts.pitch,
        )
        self.recognizer = OfflineSpeechRecognizer(
            model_path=config.stt.model_path,
            sample_rate=config.stt.sample_rate,
            listen_seconds=config.stt.listen_seconds,
        )
        self.shortcut = GlobalShortcutManager(config.hotkey)
        self.last_transcript = "Heard: waiting"
        self.shortcut_status = f"Shortcut: {config.hotkey}"
        self.listening = False
        self._pending_speech = ""
        self._speech_timer = QTimer(self.qt_app)
        self._speech_timer.setSingleShot(True)
        self._speech_timer.timeout.connect(self._flush_speech)
        tray_icon = QIcon.fromTheme("preferences-desktop-voice")
        if tray_icon.isNull():
            tray_icon = self.qt_app.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray = QSystemTrayIcon(tray_icon, self.qt_app)
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("bjcalc")
        self.qt_app.aboutToQuit.connect(self.shortcut.close)
        self._connect_signals()
        self.tray.show()
        self.shortcut.register()
        self._publish("Hold Alt+Z and say dealer, player one, player two.", "Idle", speak=False)
        if not self.speaker.available:
            self._publish("Text-to-speech is unavailable on this machine.", "TTS Error", speak=False, notify=True)

    def _build_menu(self) -> None:
        listen_action = QAction("Start Listening", self.menu)
        listen_action.triggered.connect(self.start_button_listening)
        self.menu.addAction(listen_action)

        repeat_action = QAction("Repeat Last Advice", self.menu)
        repeat_action.triggered.connect(lambda: self._speak(self.controller.last_spoken))
        self.menu.addAction(repeat_action)

        next_hand_action = QAction("Next Hand", self.menu)
        next_hand_action.triggered.connect(lambda: self._handle_command(Command.NEXT_HAND))
        self.menu.addAction(next_hand_action)

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.qt_app.quit)
        self.menu.addAction(quit_action)

    def _connect_signals(self) -> None:
        self.shortcut.activated.connect(self.start_listening)
        self.shortcut.deactivated.connect(self.stop_push_to_talk)
        self.shortcut.status_changed.connect(self._handle_shortcut_status)
        self.recognizer.phrase_ready.connect(self._handle_phrase)
        self.recognizer.error.connect(lambda text: self._publish(text, "Speech Error", notify=True))
        self.recognizer.listening_changed.connect(self._handle_listening_state)
        self.speaker.error.connect(lambda text: self._publish(text, "TTS Error", speak=False, notify=True))

    def start_listening(self) -> None:
        self._arm_controller_if_needed()
        self._cancel_speech()
        self._publish(self._listening_prompt(push_to_talk=True), "Listening", speak=False)
        self.recognizer.start_listening(push_to_talk=True, mode=self._listening_mode())

    def start_button_listening(self) -> None:
        self._arm_controller_if_needed()
        self._cancel_speech()
        self._publish(self._listening_prompt(push_to_talk=False), "Listening", speak=False)
        self.recognizer.start_listening(push_to_talk=False, mode=self._listening_mode())

    def stop_push_to_talk(self) -> None:
        self.recognizer.stop_listening()

    def _arm_controller_if_needed(self) -> None:
        if self.controller.phase == Phase.IDLE:
            reply = self.controller.arm()
            self._publish(reply.spoken, "Listening", speak=False)
        else:
            self._publish("Listening for the next phrase.", "Listening", speak=False)

    def _handle_listening_state(self, listening: bool) -> None:
        self.listening = listening
        if listening:
            self._publish(self._active_listening_status(), "Listening", speak=False)
        else:
            self._render_hud("Ready", self.hud.message.text())

    def _handle_phrase(self, text: str) -> None:
        self.last_transcript = f"Heard: {text}"
        parsed_command = parse_command_phrase(text)
        if parsed_command.command in {Command.NEXT_HAND, Command.CANCEL, Command.UNDO, Command.REPEAT}:
            self._handle_command(parsed_command.command)
            return

        phase = self.controller.phase
        if phase in {Phase.AWAIT_OPENING, Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            expected = 3 if phase == Phase.AWAIT_OPENING else 1
            parsed = parse_cards_phrase(text, expected_count=expected)
            if parsed.error:
                self._publish(parsed.error, "Parse Error", speak=False)
                return
            reply = self.controller.handle_cards(parsed.cards or [])
            self._publish(reply.display or reply.spoken, "Advice", speech_message=reply.spoken)
            return

        if parsed_command.error:
            self._publish(parsed_command.error, "Parse Error", speak=False)
            return
        self._handle_command(parsed_command.command)

    def _handle_command(self, command: Command | None) -> None:
        if command is None:
            return
        reply = self.controller.handle_command(command)
        should_speak = command is Command.REPEAT
        self._publish(reply.display or reply.spoken, "Advice", speak=should_speak, speech_message=reply.spoken)

    def _handle_shortcut_status(self, text: str) -> None:
        self.shortcut_status = text
        self._publish(text, "Shortcut", speak=False)

    def _publish(
        self,
        message: str,
        title: str,
        *,
        speak: bool = True,
        notify: bool = False,
        speech_message: str | None = None,
    ) -> None:
        self._render_hud(title, message)
        if notify:
            self.tray.showMessage("Blackjack Helper", message, QSystemTrayIcon.MessageIcon.Information, 2500)
        if speak:
            self._queue_speech(speech_message or message)

    def _render_hud(self, title: str, message: str) -> None:
        if not self.config.ui.show_hud:
            return
        status = self._status_badge(title)
        context = self._context_line()
        footer = self._footer_line()
        self.hud.render(
            status=status,
            message=message,
            context=context,
            transcript=self.last_transcript,
            footer=footer,
        )

    def _status_badge(self, title: str) -> str:
        if title in {"Parse Error", "Speech Error", "TTS Error"}:
            return title
        if self.listening:
            return "Listening"
        phase_labels = {
            Phase.IDLE: "Ready",
            Phase.AWAIT_OPENING: "Opening Hand",
            Phase.AWAIT_ACTION: "Your Action",
            Phase.AWAIT_CARD: "Waiting For Card",
            Phase.AWAIT_SPLIT_CARD: "Split Hand",
            Phase.ROUND_COMPLETE: "Round Complete",
        }
        return phase_labels.get(self.controller.phase, title)

    def _context_line(self) -> str:
        round_state = self.controller.round_state
        if round_state is None:
            return "No active hand yet."
        dealer = f"Dealer {round_state.dealer_upcard.display}"
        hands: list[str] = []
        for index, hand in enumerate(round_state.hands, start=1):
            prefix = "Now" if index - 1 == round_state.active_hand_index and not hand.finished else f"H{index}"
            suffix = " done" if hand.finished else ""
            hands.append(f"{prefix}: {hand.label()}{suffix}")
        return dealer + " | " + " | ".join(hands)

    def _footer_line(self) -> str:
        expected = self._expected_phrase()
        healthy_status = self.shortcut_status == f"Shortcut helper watching {self.config.hotkey}."
        if self.listening:
            return f"Release {self.config.hotkey} to submit."
        if healthy_status:
            return f"Push to talk: hold {self.config.hotkey}. {expected}"
        return self.shortcut_status

    def _speak(self, message: str) -> None:
        if not message or not self.speaker.available:
            return
        self.speaker.speak(message)

    def _queue_speech(self, message: str) -> None:
        self._pending_speech = message
        self._speech_timer.stop()
        self._speech_timer.start(260)

    def _flush_speech(self) -> None:
        message = self._pending_speech.strip()
        self._pending_speech = ""
        if message:
            self._speak(message)

    def _cancel_speech(self) -> None:
        self._pending_speech = ""
        self._speech_timer.stop()
        self.speaker.stop()

    def _listening_mode(self) -> ListeningMode:
        phase = self.controller.phase
        if phase == Phase.AWAIT_OPENING:
            return ListeningMode.OPENING
        if phase in {Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            return ListeningMode.CARD
        if phase == Phase.AWAIT_ACTION:
            return ListeningMode.COMMAND
        return ListeningMode.GENERIC

    def _listening_prompt(self, *, push_to_talk: bool) -> str:
        instruction = self._expected_phrase()
        if push_to_talk:
            return f"Hold {self.config.hotkey} and {instruction.lower()}, then release."
        return instruction

    def _active_listening_status(self) -> str:
        return f"Listening now. {self._expected_phrase()}"

    def _expected_phrase(self) -> str:
        phase = self.controller.phase
        if phase == Phase.AWAIT_OPENING:
            return "Say dealer card, player card one, and player card two."
        if phase == Phase.AWAIT_ACTION:
            return "Wait for the current move."
        if phase == Phase.AWAIT_CARD:
            if self.controller.pending_action == Action.DOUBLE:
                return "Say the double card."
            return "Say the drawn card."
        if phase == Phase.AWAIT_SPLIT_CARD:
            if self.controller.split_targets:
                return f"Say the replacement card for hand {self.controller.split_targets[0] + 1}."
            return "Say the replacement card."
        if phase == Phase.ROUND_COMPLETE:
            return "Say next when you are ready."
        return "Say your phrase."

    def run(self) -> int:
        return self.qt_app.exec()


def run_app() -> int:
    return BjCalcApp(load_config()).run()
