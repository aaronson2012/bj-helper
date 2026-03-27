import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bj_helper.config import AppConfig, config_path, legacy_config_path, load_config, save_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_load_config_migrates_legacy_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            path = legacy_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"recording_cue_volume": 0.7}), encoding="utf-8")

            config = load_config()

        self.assertEqual(config.recording_cue_volume, 0.7)
        self.assertFalse(path.exists())

    def test_load_config_rewrites_legacy_model_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            new_root = PROJECT_ROOT / "models"
            if not new_root.exists():
                self.skipTest("Expected bj-helper model directory is not present.")
            legacy_root = PROJECT_ROOT.parent / "bjcalc" / "models"
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
                path = config_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "stt": {"model_path": str(legacy_root / "vosk-model-small-en-us-0.15")}
                        }
                    ),
                    encoding="utf-8",
                )

                config = load_config()

        self.assertEqual(config.stt.model_path, str(new_root / "vosk-model-small-en-us-0.15"))

    def test_load_config_reads_piper_tts_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            path = config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "tts": {
                            "backend": "piper",
                            "model_path": "/models/en_US-lessac-high.onnx",
                            "speaker_id": 2,
                            "volume": 1.5,
                        },
                        "rules": {"max_split_hands": 3},
                    }
                ),
                encoding="utf-8",
            )

            config = load_config()

        self.assertEqual(config.tts.backend, "piper")
        self.assertEqual(config.tts.model_path, "/models/en_US-lessac-high.onnx")
        self.assertEqual(config.tts.speaker_id, 2)
        self.assertEqual(config.tts.volume, 1.5)
        self.assertEqual(config.rules.max_split_hands, 3)

    def test_load_config_ignores_legacy_rule_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            path = config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "rules": {
                            "peek_for_blackjack": True,
                            "max_split_hands": 4,
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_config()

        self.assertEqual(config.rules.max_split_hands, 4)

    def test_load_config_uses_explicit_repo_config_path_and_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            model_dir = Path(tmpdir) / "models"
            model_dir.mkdir(parents=True, exist_ok=True)
            cue_dir = Path(tmpdir) / "assets" / "sounds"
            cue_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "vosk").mkdir(parents=True, exist_ok=True)
            (cue_dir / "beep.mp3").write_bytes(b"beep")
            config_file.write_text(
                json.dumps(
                    {
                        "recording_cue_path": "assets/sounds/beep.mp3",
                        "stt": {"model_path": "models/vosk"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"BJ_HELPER_CONFIG": str(config_file), "XDG_CONFIG_HOME": tmpdir}, clear=False):
                config = load_config()

        self.assertEqual(config.recording_cue_path, str(cue_dir / "beep.mp3"))
        self.assertEqual(config.stt.model_path, str(model_dir / "vosk"))

    def test_save_config_persists_piper_tts_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            config = AppConfig()
            config.tts.backend = "piper"
            config.tts.model_path = "/models/en_US-lessac-high.onnx"
            config.tts.speaker_id = 1
            config.tts.volume = 1.7
            config.recording_cue_path = "/sounds/beep.mp3"
            config.recording_cue_volume = 0.2
            config.rules.max_split_hands = 4

            save_config(config)

            saved = json.loads(config_path().read_text(encoding="utf-8"))

        self.assertEqual(saved["tts"]["backend"], "piper")
        self.assertEqual(saved["tts"]["model_path"], "/models/en_US-lessac-high.onnx")
        self.assertEqual(saved["tts"]["speaker_id"], 1)
        self.assertEqual(saved["tts"]["volume"], 1.7)
        self.assertEqual(saved["recording_cue_path"], "/sounds/beep.mp3")
        self.assertEqual(saved["recording_cue_volume"], 0.2)
        self.assertEqual(saved["rules"]["max_split_hands"], 4)


if __name__ == "__main__":
    unittest.main()
