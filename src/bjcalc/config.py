from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class STTConfig:
    model_path: str = ""
    listen_seconds: float = 2.8
    sample_rate: int = 16000


@dataclass(slots=True)
class TTSConfig:
    backend: str = "speechd"
    voice: str = ""
    language: str = "en-US"
    rate: float = 0.0
    pitch: float = 0.0


@dataclass(slots=True)
class UIConfig:
    show_hud: bool = True


@dataclass(slots=True)
class RulesConfig:
    deck_mode: str = "shoe"
    dealer_soft_17: str = "hit"
    double_after_split: bool = True
    surrender: str = "late"
    insurance_enabled: bool = False
    peek_for_blackjack: bool = True


@dataclass(slots=True)
class AppConfig:
    hotkey: str = "Alt+Z"
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)


def config_path() -> Path:
    xdg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg_root / "bjcalc" / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        config = AppConfig()
        save_config(config)
        return config

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    return AppConfig(
        hotkey=raw.get("hotkey", "Alt+Z"),
        stt=STTConfig(**raw.get("stt", {})),
        tts=TTSConfig(**raw.get("tts", {})),
        ui=UIConfig(**raw.get("ui", {})),
        rules=RulesConfig(**raw.get("rules", {})),
    )


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, indent=2, sort_keys=True)
        handle.write("\n")
