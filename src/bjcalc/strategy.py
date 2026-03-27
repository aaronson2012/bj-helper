from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bjcalc.cards import CardRank, hand_value, is_pair


class Action(StrEnum):
    HIT = "hit"
    STAND = "stand"
    DOUBLE = "double"
    SPLIT = "split"
    SURRENDER = "surrender"


@dataclass(slots=True)
class RulesPreset:
    deck_mode: str = "shoe"
    dealer_soft_17: str = "hit"
    double_after_split: bool = True
    surrender: str = "late"
    insurance_enabled: bool = False
    peek_for_blackjack: bool = True


@dataclass(slots=True)
class Decision:
    action: Action
    insurance: bool | None = None
    summary: str = ""


def _dealer_value(card: CardRank) -> int:
    if card is CardRank.ACE:
        return 11
    return card.hard_value


class BasicStrategyEngine:
    def __init__(self, rules: RulesPreset) -> None:
        self.rules = rules

    def recommend(
        self,
        cards: list[CardRank],
        dealer_upcard: CardRank,
        *,
        can_double: bool,
        can_split: bool,
        can_surrender: bool,
    ) -> Decision:
        insurance = False if dealer_upcard is CardRank.ACE and self.rules.insurance_enabled else None

        if can_surrender:
            surrender_action = self._surrender_action(cards, dealer_upcard)
            if surrender_action is not None:
                return self._decision(surrender_action, insurance)

        if can_split and is_pair(cards):
            split_action = self._pair_action(cards[0], dealer_upcard)
            if split_action is Action.SPLIT:
                return self._decision(split_action, insurance)

        total, soft = hand_value(cards)
        if soft and len(cards) >= 2:
            action = self._soft_action(total, dealer_upcard, can_double)
        else:
            action = self._hard_action(total, dealer_upcard, can_double, cards)
        return self._decision(action, insurance)

    def _decision(self, action: Action, insurance: bool | None) -> Decision:
        parts = []
        if insurance is False:
            parts.append("No insurance.")
        elif insurance is True:
            parts.append("Take insurance.")
        parts.append(action.value.capitalize() + ".")
        return Decision(action=action, insurance=insurance, summary=" ".join(parts))

    def _surrender_action(self, cards: list[CardRank], dealer_upcard: CardRank) -> Action | None:
        if self.rules.surrender != "late" or len(cards) != 2:
            return None
        total, soft = hand_value(cards)
        dealer = _dealer_value(dealer_upcard)
        if soft:
            return None

        if total == 16 and dealer in {9, 10, 11}:
            return Action.SURRENDER
        if total == 15 and dealer == 10:
            return Action.SURRENDER
        return None

    def _pair_action(self, rank: CardRank, dealer_upcard: CardRank) -> Action:
        dealer = _dealer_value(dealer_upcard)
        deck_mode = self.rules.deck_mode

        if rank is CardRank.ACE:
            return Action.SPLIT
        if rank is CardRank.EIGHT:
            return Action.SPLIT
        if rank is CardRank.TEN:
            return Action.STAND
        if rank is CardRank.NINE:
            return Action.SPLIT if dealer in {2, 3, 4, 5, 6, 8, 9} else Action.STAND
        if rank is CardRank.SEVEN:
            return Action.SPLIT if dealer in {2, 3, 4, 5, 6, 7} else Action.HIT
        if rank is CardRank.SIX:
            if deck_mode == "single":
                return Action.SPLIT if dealer in {2, 3, 4, 5, 6, 7} else Action.HIT
            return Action.SPLIT if dealer in {2, 3, 4, 5, 6} else Action.HIT
        if rank is CardRank.FIVE:
            return self._hard_action(10, dealer_upcard, True, [CardRank.FIVE, CardRank.FIVE])
        if rank is CardRank.FOUR:
            if self.rules.double_after_split and dealer in {5, 6}:
                return Action.SPLIT
            return Action.HIT
        if rank is CardRank.THREE or rank is CardRank.TWO:
            if self.rules.double_after_split:
                return Action.SPLIT if dealer in {2, 3, 4, 5, 6, 7} else Action.HIT
            return Action.SPLIT if dealer in {4, 5, 6, 7} else Action.HIT
        return Action.STAND

    def _soft_action(self, total: int, dealer_upcard: CardRank, can_double: bool) -> Action:
        dealer = _dealer_value(dealer_upcard)
        if total >= 20:
            return Action.STAND
        if total == 19:
            if can_double and self.rules.deck_mode in {"single", "double"} and self.rules.dealer_soft_17 == "stand" and dealer == 6:
                return Action.DOUBLE
            return Action.STAND
        if total == 18:
            if can_double and dealer in {3, 4, 5, 6}:
                return Action.DOUBLE
            if dealer in {2, 7, 8}:
                return Action.STAND
            return Action.HIT
        if total == 17:
            return Action.DOUBLE if can_double and dealer in {3, 4, 5, 6} else Action.HIT
        if total in {15, 16}:
            return Action.DOUBLE if can_double and dealer in {4, 5, 6} else Action.HIT
        if total in {13, 14}:
            return Action.DOUBLE if can_double and dealer in {5, 6} else Action.HIT
        return Action.HIT

    def _hard_action(
        self,
        total: int,
        dealer_upcard: CardRank,
        can_double: bool,
        cards: list[CardRank],
    ) -> Action:
        dealer = _dealer_value(dealer_upcard)

        if total >= 17:
            return Action.STAND
        if 13 <= total <= 16:
            return Action.STAND if dealer in {2, 3, 4, 5, 6} else Action.HIT
        if total == 12:
            return Action.STAND if dealer in {4, 5, 6} else Action.HIT
        if total == 11:
            return Action.DOUBLE if can_double else Action.HIT
        if total == 10:
            return Action.DOUBLE if can_double and dealer in {2, 3, 4, 5, 6, 7, 8, 9} else Action.HIT
        if total == 9:
            if self.rules.deck_mode == "single":
                double_range = {2, 3, 4, 5, 6, 7}
            elif self.rules.deck_mode == "double":
                double_range = {2, 3, 4, 5, 6}
            else:
                double_range = {3, 4, 5, 6}
            return Action.DOUBLE if can_double and dealer in double_range else Action.HIT
        return Action.HIT
