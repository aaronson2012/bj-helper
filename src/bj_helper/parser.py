from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bj_helper.cards import CARD_ALIASES, CardRank
from bj_helper.debug import log_debug


class Command(StrEnum):
    REPEAT = "repeat"
    UNDO = "undo"
    CANCEL = "cancel"
    NEXT_HAND = "next_hand"


COMMAND_ALIASES: dict[str, Command] = {
    "repeat": Command.REPEAT,
    "say again": Command.REPEAT,
    "undo": Command.UNDO,
    "cancel": Command.CANCEL,
    "next": Command.NEXT_HAND,
    "next hand": Command.NEXT_HAND,
    "new hand": Command.NEXT_HAND,
    "reset": Command.NEXT_HAND,
}


@dataclass(slots=True)
class SpeechParseResult:
    cards: list[CardRank] | None = None
    command: Command | None = None
    error: str | None = None


def normalize_text(text: str) -> str:
    cleaned = text.lower().strip()
    for ch in ",.;:/\\|-_":
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


def parse_cards_phrase(text: str, expected_count: int | None = None) -> SpeechParseResult:
    normalized = normalize_text(text)
    if not normalized:
        result = SpeechParseResult(error="No cards were heard.")
        log_debug("parse_cards", raw=text, normalized=normalized, expected_count=expected_count, error=result.error)
        return result

    cards: list[CardRank] = []
    for token in normalized.split():
        card = CARD_ALIASES.get(token)
        if card is None:
            result = SpeechParseResult(error=f"Unrecognized card word: {token}")
            log_debug("parse_cards", raw=text, normalized=normalized, expected_count=expected_count, error=result.error)
            return result
        cards.append(card)

    if expected_count is not None and len(cards) != expected_count:
        result = SpeechParseResult(error=f"Expected {expected_count} cards, heard {len(cards)}.")
        log_debug("parse_cards", raw=text, normalized=normalized, expected_count=expected_count, cards=[card.name for card in cards], error=result.error)
        return result
    result = SpeechParseResult(cards=cards)
    log_debug("parse_cards", raw=text, normalized=normalized, expected_count=expected_count, cards=[card.name for card in cards])
    return result


def parse_command_phrase(text: str) -> SpeechParseResult:
    normalized = normalize_text(text)
    if not normalized:
        result = SpeechParseResult(error="No command was heard.")
        log_debug("parse_command", raw=text, normalized=normalized, error=result.error)
        return result

    command = COMMAND_ALIASES.get(normalized)
    if command is None:
        result = SpeechParseResult(error=f"Unrecognized command: {normalized}")
        log_debug("parse_command", raw=text, normalized=normalized, error=result.error)
        return result
    result = SpeechParseResult(command=command)
    log_debug("parse_command", raw=text, normalized=normalized, command=command.value)
    return result
