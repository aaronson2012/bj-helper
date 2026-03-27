from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bjcalc.cards import CARD_ALIASES, CardRank


class Command(StrEnum):
    HIT = "hit"
    STAND = "stand"
    DOUBLE = "double"
    SPLIT = "split"
    SURRENDER = "surrender"
    INSURANCE = "insurance"
    REPEAT = "repeat"
    UNDO = "undo"
    CANCEL = "cancel"
    NEXT_HAND = "next_hand"


COMMAND_ALIASES: dict[str, Command] = {
    "hit": Command.HIT,
    "stand": Command.STAND,
    "stay": Command.STAND,
    "double": Command.DOUBLE,
    "double down": Command.DOUBLE,
    "split": Command.SPLIT,
    "surrender": Command.SURRENDER,
    "insurance": Command.INSURANCE,
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
        return SpeechParseResult(error="No cards were heard.")

    cards: list[CardRank] = []
    for token in normalized.split():
        card = CARD_ALIASES.get(token)
        if card is None:
            return SpeechParseResult(error=f"Unrecognized card word: {token}")
        cards.append(card)

    if expected_count is not None and len(cards) != expected_count:
        return SpeechParseResult(error=f"Expected {expected_count} cards, heard {len(cards)}.")
    return SpeechParseResult(cards=cards)


def parse_command_phrase(text: str) -> SpeechParseResult:
    normalized = normalize_text(text)
    if not normalized:
        return SpeechParseResult(error="No command was heard.")

    command = COMMAND_ALIASES.get(normalized)
    if command is None:
        return SpeechParseResult(error=f"Unrecognized command: {normalized}")
    return SpeechParseResult(command=command)
