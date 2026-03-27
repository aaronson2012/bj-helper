from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from bj_helper.debug import log_debug


@dataclass(slots=True)
class STTConfig:
    model_path: str = ""
    listen_seconds: float = 3.0
    sample_rate: int = 16000


@dataclass(slots=True)
class TTSConfig:
    backend: str = "speechd"
    voice: str = ""
    language: str = "en-US"
    rate: float = 0.0
    pitch: float = 0.0
    volume: float = 1.0
    model_path: str = ""
    speaker_id: int | None = None


@dataclass(slots=True)
class RulesConfig:
    deck_mode: str = "shoe"
    dealer_soft_17: str = "hit"
    double_after_split: bool = True
    max_split_hands: int = 4
    surrender: str = "none"
    insurance_enabled: bool = False


@dataclass(slots=True)
class AppConfig:
    recording_cue_path: str = ""
    recording_cue_volume: float = 0.8
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)


def _explicit_config_path() -> Path | None:
    configured = os.environ.get("BJ_HELPER_CONFIG", "").strip()
    return Path(configured).expanduser() if configured else None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    explicit_path = _explicit_config_path()
    if explicit_path is not None:
        return explicit_path
    return _user_config_path()


def _user_config_path() -> Path:
    xdg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg_root / "bj-helper" / "config.json"


def legacy_config_path() -> Path:
    xdg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg_root / "bjcalc" / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    explicit_path = _explicit_config_path()
    log_debug("config_load_start", config_path=str(path), explicit_path=str(explicit_path) if explicit_path else "")
    if explicit_path is None and not path.exists():
        _migrate_legacy_config()

    raw: dict = {}
    if explicit_path is not None:
        if explicit_path.exists():
            raw = _load_raw_config(explicit_path)
        user_path = _user_config_path()
        if user_path.exists():
            raw = _merge_dicts(raw, _load_raw_config(user_path))
    else:
        if not path.exists():
            config = AppConfig()
            save_config(config)
            log_debug("config_created_default", config_path=str(path))
            return config
        raw = _load_raw_config(path)

    config = AppConfig(
        recording_cue_path=raw.get("recording_cue_path", ""),
        recording_cue_volume=raw.get("recording_cue_volume", 0.8),
        stt=STTConfig(**_known_keys(raw.get("stt", {}), STTConfig)),
        tts=TTSConfig(**_known_keys(raw.get("tts", {}), TTSConfig)),
        rules=RulesConfig(**_known_keys(raw.get("rules", {}), RulesConfig)),
    )
    log_debug(
        "config_loaded",
        config_path=str(path),
        cue_path=config.recording_cue_path,
        cue_volume=config.recording_cue_volume,
        stt_model=config.stt.model_path,
        stt_listen_seconds=config.stt.listen_seconds,
        stt_sample_rate=config.stt.sample_rate,
        tts_backend=config.tts.backend,
        tts_model=config.tts.model_path,
        tts_voice=config.tts.voice,
        tts_volume=config.tts.volume,
        rules=asdict(config.rules),
    )
    return config


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, indent=2, sort_keys=True)
        handle.write("\n")
    log_debug("config_saved", config_path=str(path))


def _migrate_legacy_config() -> None:
    legacy_path = legacy_config_path()
    new_path = _user_config_path()
    if not legacy_path.exists() or new_path.exists():
        return
    new_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.replace(new_path)
    try:
        legacy_path.parent.rmdir()
    except OSError:
        pass
    log_debug("config_migrated_legacy", legacy_path=str(legacy_path), new_path=str(new_path))


def _normalize_paths(raw: dict, base_dir: Path) -> None:
    stt = raw.get("stt")
    if isinstance(stt, dict):
        model_path = stt.get("model_path")
        if isinstance(model_path, str):
            stt["model_path"] = _normalize_path(model_path, base_dir)
    tts = raw.get("tts")
    if isinstance(tts, dict):
        model_path = tts.get("model_path")
        if isinstance(model_path, str):
            tts["model_path"] = _normalize_path(model_path, base_dir)
    recording_cue_path = raw.get("recording_cue_path")
    if isinstance(recording_cue_path, str):
        raw["recording_cue_path"] = _normalize_path(recording_cue_path, base_dir)


def _normalize_path(path_text: str, base_dir: Path) -> str:
    if not path_text:
        return path_text
    candidate = _rewrite_legacy_path(path_text)
    if candidate != path_text:
        path_text = candidate
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _rewrite_legacy_path(path_text: str) -> str:
    legacy_marker = f"{os.sep}bjcalc{os.sep}"
    if legacy_marker not in path_text:
        return path_text
    suffix = path_text.split(legacy_marker, 1)[1]
    candidate = str(_project_root() / suffix)
    return candidate if Path(candidate).exists() else path_text


def _load_raw_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    _normalize_paths(raw, path.parent)
    log_debug("config_raw_loaded", config_path=str(path), keys=sorted(raw.keys()))
    return raw


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _known_keys(raw_section: object, config_type: type) -> dict:
    if not isinstance(raw_section, dict):
        return {}
    allowed = {field.name for field in fields(config_type)}
    filtered = {key: value for key, value in raw_section.items() if key in allowed}
    ignored = sorted(key for key in raw_section if key not in allowed)
    if ignored:
        log_debug("config_ignored_keys", section=config_type.__name__, keys=ignored)
    return filtered
