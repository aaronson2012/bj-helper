import os
import unittest
from unittest.mock import patch

from bj_helper.speech import ListeningMode, OfflineSpeechRecognizer, TextSpeaker


class _CompletedRun:
    returncode = 0
    stderr = ""


class _PlaybackProcess:
    def __init__(self) -> None:
        self.pid = 67890

    def poll(self) -> int | None:
        return 0

    def wait(self) -> int:
        return 0


class SpeechTests(unittest.TestCase):
    def test_card_grammar_includes_invalid_number_words_and_control_words(self) -> None:
        recognizer = OfflineSpeechRecognizer("model", sample_rate=16000, listen_seconds=3.0)

        grammar = recognizer._grammar_for_mode(ListeningMode.OPENING)

        self.assertIn("one", grammar)
        self.assertIn("won", grammar)
        self.assertIn("eleven", grammar)
        self.assertIn("next", grammar)

    def test_piper_output_file_exists_when_playback_starts(self) -> None:
        with patch.object(TextSpeaker, "_can_use_piper", return_value=True):
            speaker = TextSpeaker(backend="piper", model_path="/tmp/model.onnx")

        seen: dict[str, object] = {}

        def fake_run(command, **_kwargs):
            output_path = command[command.index("--output_file") + 1]
            with open(output_path, "wb") as handle:
                handle.write(b"RIFFdemoWAVE")
            return _CompletedRun()

        def fake_popen(command, **_kwargs):
            path = command[-1]
            seen["exists_at_start"] = os.path.exists(path)
            seen["path"] = path
            return _PlaybackProcess()

        with (
            patch.object(speaker, "_piper_executable", return_value="piper-tts"),
            patch.object(speaker, "_playback_command", side_effect=lambda output_path: ["paplay", output_path]),
            patch("subprocess.run", side_effect=fake_run),
            patch("subprocess.Popen", side_effect=fake_popen),
        ):
            speaker.speak("Double.")

        self.assertTrue(seen.get("exists_at_start"))


if __name__ == "__main__":
    unittest.main()
