from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import StrEnum

from bjcalc.cards import CardRank, format_cards, hand_value, is_blackjack, is_pair
from bjcalc.parser import Command
from bjcalc.strategy import Action, BasicStrategyEngine, Decision, RulesPreset


class Phase(StrEnum):
    IDLE = "idle"
    AWAIT_OPENING = "await_opening"
    AWAIT_ACTION = "await_action"
    AWAIT_CARD = "await_card"
    AWAIT_SPLIT_CARD = "await_split_card"
    ROUND_COMPLETE = "round_complete"


@dataclass(slots=True)
class HandState:
    cards: list[CardRank]
    finished: bool = False
    surrendered: bool = False
    doubled: bool = False
    split_hand: bool = False

    def label(self) -> str:
        total, soft = hand_value(self.cards)
        prefix = "soft " if soft and total <= 21 else ""
        return f"{format_cards(self.cards)} ({prefix}{total})"


@dataclass(slots=True)
class RoundState:
    dealer_upcard: CardRank
    hands: list[HandState]
    active_hand_index: int = 0
    insurance_taken: bool = False


@dataclass(slots=True)
class Snapshot:
    phase: Phase
    round_state: RoundState | None
    pending_action: Action | None
    split_targets: list[int]
    last_spoken: str


@dataclass(slots=True)
class ControllerReply:
    spoken: str
    phase: Phase
    display: str | None = None


@dataclass(slots=True)
class BlackjackController:
    rules: RulesPreset
    engine: BasicStrategyEngine = field(init=False)
    phase: Phase = Phase.IDLE
    round_state: RoundState | None = None
    pending_action: Action | None = None
    split_targets: list[int] = field(default_factory=list)
    history: list[Snapshot] = field(default_factory=list)
    last_spoken: str = "Ready."

    def __post_init__(self) -> None:
        self.engine = BasicStrategyEngine(self.rules)

    def arm(self) -> ControllerReply:
        if self.phase in {Phase.AWAIT_ACTION, Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            return self._reply("Hand already active.")
        self.phase = Phase.AWAIT_OPENING
        self.round_state = None
        self.pending_action = None
        self.split_targets = []
        self.history.clear()
        return self._reply("Listening for dealer card, player card one, and player card two.")

    def handle_cards(self, cards: list[CardRank]) -> ControllerReply:
        if self.phase == Phase.AWAIT_OPENING:
            if len(cards) != 3:
                return self._reply("Say exactly three cards for the opening hand.")
            self._push_history()
            dealer, first, second = cards
            self.round_state = RoundState(dealer_upcard=dealer, hands=[HandState(cards=[first, second])])
            return self._advance_to_decision()

        if self.phase == Phase.AWAIT_CARD:
            if len(cards) != 1:
                return self._reply("Say exactly one card.")
            self._push_history()
            assert self.round_state is not None
            hand = self._active_hand()
            hand.cards.append(cards[0])
            if self.pending_action is Action.DOUBLE:
                hand.doubled = True
                hand.finished = True
                self.pending_action = None
                return self._advance_after_draw()
            self.pending_action = None
            total, _ = hand_value(hand.cards)
            if total >= 21:
                hand.finished = True
                return self._advance_after_draw()
            return self._advance_to_decision()

        if self.phase == Phase.AWAIT_SPLIT_CARD:
            if len(cards) != 1:
                return self._reply("Say exactly one card for the split hand.")
            self._push_history()
            assert self.round_state is not None
            target_index = self.split_targets.pop(0)
            self.round_state.hands[target_index].cards.append(cards[0])
            if self.split_targets:
                next_label = self.split_targets[0] + 1
                return self._reply(f"Say the replacement card for hand {next_label}.")
            self.round_state.active_hand_index = 0
            return self._advance_to_decision()

        return self._reply("I was not expecting cards right now.")

    def handle_command(self, command: Command) -> ControllerReply:
        if command is Command.REPEAT:
            return self._reply(self.last_spoken)
        if command is Command.CANCEL:
            self._reset("Hand cancelled.")
            return self._reply(self.last_spoken)
        if command is Command.NEXT_HAND:
            self._reset("Ready for the next hand.")
            return self._reply(self.last_spoken)
        if command is Command.UNDO:
            return self._undo()

        if self.round_state is None or self.phase not in {Phase.AWAIT_ACTION, Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            return self._reply("No active hand.")

        if command is Command.INSURANCE:
            if self.round_state.dealer_upcard is not CardRank.ACE or not self.rules.insurance_enabled:
                return self._reply("Insurance is not available.")
            self._push_history()
            self.round_state.insurance_taken = True
            return self._reply("Insurance noted. Say your main action.")

        if self.phase != Phase.AWAIT_ACTION:
            return self._reply("Say the next card value first.")

        action_map = {
            Command.HIT: Action.HIT,
            Command.STAND: Action.STAND,
            Command.DOUBLE: Action.DOUBLE,
            Command.SPLIT: Action.SPLIT,
            Command.SURRENDER: Action.SURRENDER,
        }
        action = action_map.get(command)
        if action is None:
            return self._reply("That command is not valid here.")

        legal_actions = self._legal_actions()
        if action not in legal_actions:
            return self._reply(f"{action.value.capitalize()} is not legal for this hand.")

        self._push_history()
        if action is Action.STAND:
            self._active_hand().finished = True
            return self._advance_to_next_hand()
        if action is Action.SURRENDER:
            hand = self._active_hand()
            hand.surrendered = True
            hand.finished = True
            return self._advance_to_next_hand()
        if action is Action.HIT:
            self.pending_action = Action.HIT
            self.phase = Phase.AWAIT_CARD
            return self._reply("Say the drawn card.")
        if action is Action.DOUBLE:
            self.pending_action = Action.DOUBLE
            self.phase = Phase.AWAIT_CARD
            return self._reply("Say the double card.")
        if action is Action.SPLIT:
            return self._handle_split()
        return self._reply("Unsupported action.")

    def _handle_split(self) -> ControllerReply:
        assert self.round_state is not None
        hand = self._active_hand()
        first, second = hand.cards
        replacement_hands = [
            HandState(cards=[first], split_hand=True),
            HandState(cards=[second], split_hand=True),
        ]
        self.round_state.hands[self.round_state.active_hand_index : self.round_state.active_hand_index + 1] = replacement_hands
        base = self.round_state.active_hand_index
        self.split_targets = [base, base + 1]
        self.phase = Phase.AWAIT_SPLIT_CARD
        return self._reply(f"Say the replacement card for hand {base + 1}.")

    def _advance_after_draw(self) -> ControllerReply:
        if self._active_hand().finished:
            return self._advance_to_next_hand()
        return self._advance_to_decision()

    def _advance_to_next_hand(self) -> ControllerReply:
        assert self.round_state is not None
        for index, hand in enumerate(self.round_state.hands):
            if not hand.finished:
                self.round_state.active_hand_index = index
                return self._advance_to_decision()
        self.phase = Phase.ROUND_COMPLETE
        return self._reply("Round complete.", display="Round complete. Say next when you are ready.")

    def _active_hand(self) -> HandState:
        assert self.round_state is not None
        return self.round_state.hands[self.round_state.active_hand_index]

    def _legal_actions(self) -> set[Action]:
        assert self.round_state is not None
        hand = self._active_hand()
        actions = {Action.HIT, Action.STAND}
        if len(hand.cards) == 2:
            can_double = not hand.split_hand or self.rules.double_after_split
            if can_double:
                actions.add(Action.DOUBLE)
            if self.rules.surrender == "late" and not hand.split_hand:
                actions.add(Action.SURRENDER)
            if is_pair(hand.cards):
                actions.add(Action.SPLIT)
        return actions

    def _current_recommendation(self) -> Decision:
        assert self.round_state is not None
        hand = self._active_hand()
        return self.engine.recommend(
            hand.cards,
            self.round_state.dealer_upcard,
            can_double=Action.DOUBLE in self._legal_actions(),
            can_split=Action.SPLIT in self._legal_actions(),
            can_surrender=Action.SURRENDER in self._legal_actions(),
        )

    def _current_recommendation_texts(self) -> tuple[str, str]:
        assert self.round_state is not None
        hand = self._active_hand()
        recommendation = self._current_recommendation()
        intro = f"Dealer {self.round_state.dealer_upcard.display}. Hand {self.round_state.active_hand_index + 1}: {hand.label()}."
        if is_blackjack(hand.cards):
            return "Blackjack.", f"{intro} Blackjack."
        spoken = recommendation.action.value.capitalize() + "."
        return spoken, f"{intro} {recommendation.summary}"

    def _advance_to_decision(self) -> ControllerReply:
        assert self.round_state is not None
        spoken_parts: list[str] = []
        display = ""

        while True:
            hand = self._active_hand()
            recommendation = self._current_recommendation()
            display = self._display_text_for(recommendation)

            if is_blackjack(hand.cards):
                hand.finished = True
                spoken_parts.append("Blackjack.")
                if all(current.finished for current in self.round_state.hands):
                    self.phase = Phase.ROUND_COMPLETE
                    return self._reply(" ".join(spoken_parts), display=display)
                reply = self._advance_to_next_hand()
                spoken = " ".join(spoken_parts + [reply.spoken]).strip()
                return self._reply(spoken, display=reply.display)

            if recommendation.action is Action.HIT:
                self.pending_action = Action.HIT
                self.phase = Phase.AWAIT_CARD
                spoken_parts.append("Hit.")
                return self._reply(" ".join(spoken_parts), display=display)

            if recommendation.action is Action.DOUBLE:
                self.pending_action = Action.DOUBLE
                self.phase = Phase.AWAIT_CARD
                spoken_parts.append("Double.")
                return self._reply(" ".join(spoken_parts), display=display)

            if recommendation.action is Action.SPLIT:
                self.pending_action = None
                self._apply_split()
                spoken_parts.append("Split.")
                return self._reply(" ".join(spoken_parts), display=display)

            if recommendation.action is Action.STAND:
                hand.finished = True
                spoken_parts.append("Stand.")
            elif recommendation.action is Action.SURRENDER:
                hand.surrendered = True
                hand.finished = True
                spoken_parts.append("Surrender.")
            else:
                return self._reply("Unsupported action.", display=display)

            unfinished = [index for index, current in enumerate(self.round_state.hands) if not current.finished]
            if not unfinished:
                self.phase = Phase.ROUND_COMPLETE
                return self._reply(" ".join(spoken_parts), display=display)
            self.round_state.active_hand_index = unfinished[0]

    def _remember(self, text: str) -> str:
        self.last_spoken = text
        return text

    def _push_history(self) -> None:
        self.history.append(
            Snapshot(
                phase=self.phase,
                round_state=copy.deepcopy(self.round_state),
                pending_action=self.pending_action,
                split_targets=list(self.split_targets),
                last_spoken=self.last_spoken,
            )
        )

    def _undo(self) -> ControllerReply:
        if not self.history:
            return self._reply("Nothing to undo.")
        snapshot = self.history.pop()
        self.phase = snapshot.phase
        self.round_state = copy.deepcopy(snapshot.round_state)
        self.pending_action = snapshot.pending_action
        self.split_targets = list(snapshot.split_targets)
        self.last_spoken = snapshot.last_spoken
        return self._reply("Undid the last step. " + self.last_spoken)

    def _reset(self, message: str) -> None:
        self.phase = Phase.IDLE
        self.round_state = None
        self.pending_action = None
        self.split_targets.clear()
        self.history.clear()
        self._remember(message)

    def _reply(self, spoken: str, *, display: str | None = None) -> ControllerReply:
        return ControllerReply(self._remember(spoken), self.phase, display or spoken)

    def _apply_split(self) -> None:
        assert self.round_state is not None
        hand = self._active_hand()
        first, second = hand.cards
        replacement_hands = [
            HandState(cards=[first], split_hand=True),
            HandState(cards=[second], split_hand=True),
        ]
        base = self.round_state.active_hand_index
        self.round_state.hands[base : base + 1] = replacement_hands
        self.split_targets = [base, base + 1]
        self.phase = Phase.AWAIT_SPLIT_CARD

    def _display_text_for(self, recommendation: Decision) -> str:
        assert self.round_state is not None
        hand = self._active_hand()
        intro = f"Dealer {self.round_state.dealer_upcard.display}. Hand {self.round_state.active_hand_index + 1}: {hand.label()}."
        if is_blackjack(hand.cards):
            return f"{intro} Blackjack."
        return f"{intro} {recommendation.summary}"
