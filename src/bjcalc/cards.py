from __future__ import annotations

from enum import StrEnum


class CardRank(StrEnum):
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    ACE = "A"

    @property
    def hard_value(self) -> int:
        if self is CardRank.ACE:
            return 1
        return min(int(self.value), 10)

    @property
    def display(self) -> str:
        labels = {
            CardRank.ACE: "Ace",
            CardRank.TEN: "10",
        }
        return labels.get(self, self.value)


CARD_ALIASES: dict[str, CardRank] = {
    "2": CardRank.TWO,
    "two": CardRank.TWO,
    "to": CardRank.TWO,
    "too": CardRank.TWO,
    "3": CardRank.THREE,
    "three": CardRank.THREE,
    "4": CardRank.FOUR,
    "four": CardRank.FOUR,
    "for": CardRank.FOUR,
    "5": CardRank.FIVE,
    "five": CardRank.FIVE,
    "6": CardRank.SIX,
    "six": CardRank.SIX,
    "7": CardRank.SEVEN,
    "seven": CardRank.SEVEN,
    "8": CardRank.EIGHT,
    "eight": CardRank.EIGHT,
    "ate": CardRank.EIGHT,
    "9": CardRank.NINE,
    "nine": CardRank.NINE,
    "10": CardRank.TEN,
    "ten": CardRank.TEN,
    "jack": CardRank.TEN,
    "queen": CardRank.TEN,
    "king": CardRank.TEN,
    "ace": CardRank.ACE,
}


def hand_value(cards: list[CardRank]) -> tuple[int, bool]:
    total = sum(card.hard_value for card in cards)
    aces = sum(1 for card in cards if card is CardRank.ACE)
    soft = False
    while aces and total + 10 <= 21:
        total += 10
        aces -= 1
        soft = True
    return total, soft


def is_blackjack(cards: list[CardRank]) -> bool:
    total, _ = hand_value(cards)
    return len(cards) == 2 and total == 21


def is_pair(cards: list[CardRank]) -> bool:
    return len(cards) == 2 and cards[0] == cards[1]


def format_cards(cards: list[CardRank]) -> str:
    return " ".join(card.display for card in cards)
