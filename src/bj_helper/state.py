from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import StrEnum

from bj_helper.cards import CardRank, format_cards, hand_value, is_blackjack, is_pair
from bj_helper.debug import log_debug
from bj_helper.parser import Command
from bj_helper.strategy import Action, BasicStrategyEngine, Decision, RulesPreset


class Phase(StrEnum):
    IDLE = "idle"
    AWAIT_OPENING = "await_opening"
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
    split_aces: bool = False

    def label(self) -> str:
        total, soft = hand_value(self.cards)
        prefix = "soft " if soft and total <= 21 else ""
        return f"{format_cards(self.cards)} ({prefix}{total})"


@dataclass(slots=True)
class RoundState:
    dealer_upcard: CardRank
    hands: list[HandState]
    active_hand_index: int = 0


@dataclass(slots=True)
class Snapshot:
    phase: Phase
    round_state: RoundState | None
    pending_action: Action | None
    split_targets: list[int]
    last_spoken: str
    last_advice: str


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
    last_advice: str = ""

    def __post_init__(self) -> None:
        self.engine = BasicStrategyEngine(self.rules)
        log_debug("controller_initialized", phase=self.phase.value, rules=self.rules)

    def arm(self) -> ControllerReply:
        log_debug("controller_arm", prior_phase=self.phase.value)
        if self.phase in {Phase.AWAIT_CARD, Phase.AWAIT_SPLIT_CARD}:
            return self._reply("Hand already active.")
        self.phase = Phase.AWAIT_OPENING
        self.round_state = None
        self.pending_action = None
        self.split_targets = []
        self.history.clear()
        self.last_advice = ""
        return self._reply("Listening for dealer card, player card one, and player card two.")

    def handle_cards(self, cards: list[CardRank]) -> ControllerReply:
        log_debug(
            "controller_handle_cards",
            phase=self.phase.value,
            cards=[card.name for card in cards],
            pending_action=self.pending_action.value if self.pending_action else "",
        )
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
            target_hand = self.round_state.hands[target_index]
            target_hand.cards.append(cards[0])
            if target_hand.split_aces:
                target_hand.finished = True
                log_debug("controller_split_aces_locked", hand_index=target_index, hand=target_hand.label())
            if self.split_targets:
                next_label = self.split_targets[0] + 1
                return self._reply(f"Say the replacement card for hand {next_label}.")
            self.round_state.active_hand_index = 0
            if all(hand.finished for hand in self.round_state.hands):
                self.phase = Phase.ROUND_COMPLETE
                return self._reply(
                    "Stand.",
                    display=self._action_display_for_hand(target_index, "Stand."),
                    remember_advice=True,
                )
            if self.round_state.hands[self.round_state.active_hand_index].finished:
                return self._advance_to_next_hand()
            return self._advance_to_decision()

        return self._reply("I was not expecting cards right now.")

    def handle_command(self, command: Command) -> ControllerReply:
        log_debug(
            "controller_handle_command",
            command=command.value,
            phase=self.phase.value,
            pending_action=self.pending_action.value if self.pending_action else "",
            has_round=self.round_state is not None,
            last_advice=self.last_advice,
        )
        if command is Command.REPEAT:
            if self.last_advice:
                return self._reply(self.last_advice)
            return self._reply("No advice to repeat.")
        if command is Command.CANCEL:
            self._reset("Hand cancelled.")
            return self._reply(self.last_spoken)
        if command is Command.NEXT_HAND:
            self._reset("Ready for the next hand.")
            return self._reply(self.last_spoken)
        if command is Command.UNDO:
            return self._undo()
        return self._reply("That command is not supported.")

    def _handle_split(self) -> ControllerReply:
        if Action.SPLIT not in self._legal_actions():
            return self._reply("Split is not legal for this hand.")
        self._split_active_hand()
        assert self.round_state is not None
        return self._reply(f"Say the replacement card for hand {self.round_state.active_hand_index + 1}.")

    def _split_active_hand(self) -> None:
        assert self.round_state is not None
        hand = self._active_hand()
        log_debug(
            "controller_split",
            active_hand_index=self.round_state.active_hand_index,
            cards=[card.name for card in hand.cards],
            total_hands_before=len(self.round_state.hands),
            max_split_hands=self.rules.max_split_hands,
        )
        first, second = hand.cards
        split_aces = first is CardRank.ACE and second is CardRank.ACE
        replacement_hands = [
            HandState(cards=[first], split_hand=True, split_aces=split_aces),
            HandState(cards=[second], split_hand=True, split_aces=split_aces),
        ]
        self.round_state.hands[self.round_state.active_hand_index : self.round_state.active_hand_index + 1] = replacement_hands
        base = self.round_state.active_hand_index
        self.split_targets = [base, base + 1]
        self.phase = Phase.AWAIT_SPLIT_CARD
        log_debug(
            "controller_split_applied",
            active_hand_index=base,
            total_hands_after=len(self.round_state.hands),
            split_targets=self.split_targets,
            split_aces=split_aces,
        )

    def _advance_after_draw(self) -> ControllerReply:
        log_debug("controller_advance_after_draw", hand_finished=self._active_hand().finished)
        if self._active_hand().finished:
            return self._advance_to_next_hand()
        return self._advance_to_decision()

    def _advance_to_next_hand(self) -> ControllerReply:
        assert self.round_state is not None
        log_debug(
            "controller_advance_to_next_hand",
            active_hand_index=self.round_state.active_hand_index,
            hand_states=[hand.label() for hand in self.round_state.hands],
            finished=[hand.finished for hand in self.round_state.hands],
        )
        for index, hand in enumerate(self.round_state.hands):
            if not hand.finished:
                self.round_state.active_hand_index = index
                log_debug("controller_next_hand_selected", next_hand_index=index)
                return self._advance_to_decision()
        self.phase = Phase.ROUND_COMPLETE
        log_debug("controller_round_complete")
        return self._reply("Round complete.", display="Round complete.")

    def _active_hand(self) -> HandState:
        assert self.round_state is not None
        return self.round_state.hands[self.round_state.active_hand_index]

    def _legal_actions(self) -> set[Action]:
        assert self.round_state is not None
        hand = self._active_hand()
        total_hands = len(self.round_state.hands)
        if hand.split_aces:
            actions = {Action.STAND}
            log_debug(
                "controller_legal_actions",
                hand=hand.label(),
                actions=sorted(action.value for action in actions),
                total_hands=total_hands,
                max_split_hands=self.rules.max_split_hands,
            )
            return actions
        actions = {Action.HIT, Action.STAND}
        if len(hand.cards) == 2:
            can_double = not hand.split_hand or self.rules.double_after_split
            if can_double:
                actions.add(Action.DOUBLE)
            if self.rules.surrender == "late" and not hand.split_hand:
                actions.add(Action.SURRENDER)
            if is_pair(hand.cards) and total_hands < self.rules.max_split_hands:
                actions.add(Action.SPLIT)
        log_debug(
            "controller_legal_actions",
            hand=hand.label(),
            actions=sorted(action.value for action in actions),
            total_hands=total_hands,
            max_split_hands=self.rules.max_split_hands,
        )
        return actions

    def _current_recommendation(self) -> Decision:
        assert self.round_state is not None
        hand = self._active_hand()
        decision = self.engine.recommend(
            hand.cards,
            self.round_state.dealer_upcard,
            can_double=Action.DOUBLE in self._legal_actions(),
            can_split=Action.SPLIT in self._legal_actions(),
            can_surrender=Action.SURRENDER in self._legal_actions(),
        )
        log_debug(
            "controller_recommendation",
            hand=hand.label(),
            dealer_upcard=self.round_state.dealer_upcard.name,
            action=decision.action.value,
            summary=decision.summary,
        )
        return decision

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
        log_debug(
            "controller_advance_to_decision",
            active_hand_index=self.round_state.active_hand_index,
            hands=[hand.label() for hand in self.round_state.hands],
        )

        while True:
            hand = self._active_hand()
            recommendation = self._current_recommendation()
            display = self._display_text_for(recommendation)

            if is_blackjack(hand.cards):
                hand.finished = True
                spoken_parts.append("Blackjack.")
                if all(current.finished for current in self.round_state.hands):
                    self.phase = Phase.ROUND_COMPLETE
                    return self._reply(" ".join(spoken_parts), display=display, remember_advice=True)
                reply = self._advance_to_next_hand()
                spoken = " ".join(spoken_parts + [reply.spoken]).strip()
                return self._reply(spoken, display=reply.display, remember_advice=True)

            if recommendation.action is Action.HIT:
                self.pending_action = Action.HIT
                self.phase = Phase.AWAIT_CARD
                spoken_parts.append("Hit.")
                return self._reply(" ".join(spoken_parts), display=display, remember_advice=True)

            if recommendation.action is Action.DOUBLE:
                self.pending_action = Action.DOUBLE
                self.phase = Phase.AWAIT_CARD
                spoken_parts.append("Double.")
                return self._reply(" ".join(spoken_parts), display=display, remember_advice=True)

            if recommendation.action is Action.SPLIT:
                self.pending_action = None
                self._apply_split()
                spoken_parts.append("Split.")
                return self._reply(" ".join(spoken_parts), display=display, remember_advice=True)

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
                return self._reply(" ".join(spoken_parts), display=display, remember_advice=True)
            self.round_state.active_hand_index = unfinished[0]

    def _remember(self, text: str) -> str:
        self.last_spoken = text
        return text

    def _push_history(self) -> None:
        log_debug("controller_push_history", history_size=len(self.history) + 1, phase=self.phase.value)
        self.history.append(
            Snapshot(
                phase=self.phase,
                round_state=copy.deepcopy(self.round_state),
                pending_action=self.pending_action,
                split_targets=list(self.split_targets),
                last_spoken=self.last_spoken,
                last_advice=self.last_advice,
            )
        )

    def _undo(self) -> ControllerReply:
        if not self.history:
            return self._reply("Nothing to undo.")
        snapshot = self.history.pop()
        log_debug("controller_undo", history_size=len(self.history), restore_phase=snapshot.phase.value)
        self.phase = snapshot.phase
        self.round_state = copy.deepcopy(snapshot.round_state)
        self.pending_action = snapshot.pending_action
        self.split_targets = list(snapshot.split_targets)
        self.last_spoken = snapshot.last_spoken
        self.last_advice = snapshot.last_advice
        return self._reply("Undid the last step. " + self.last_spoken)

    def _reset(self, message: str) -> None:
        log_debug("controller_reset", message=message, prior_phase=self.phase.value)
        self.phase = Phase.IDLE
        self.round_state = None
        self.pending_action = None
        self.split_targets.clear()
        self.history.clear()
        self.last_advice = ""
        self._remember(message)

    def _reply(self, spoken: str, *, display: str | None = None, remember_advice: bool = False) -> ControllerReply:
        if remember_advice:
            self.last_advice = spoken
        reply = ControllerReply(self._remember(spoken), self.phase, display or spoken)
        log_debug(
            "controller_reply",
            phase=self.phase.value,
            spoken=reply.spoken,
            display=reply.display,
            remember_advice=remember_advice,
            last_advice=self.last_advice,
        )
        return reply

    def _apply_split(self) -> None:
        self._split_active_hand()

    def _action_display_for_hand(self, hand_index: int, action_text: str) -> str:
        assert self.round_state is not None
        hand = self.round_state.hands[hand_index]
        return f"Dealer {self.round_state.dealer_upcard.display}. Hand {hand_index + 1}: {hand.label()}. {action_text}"

    def _display_text_for(self, recommendation: Decision) -> str:
        assert self.round_state is not None
        hand = self._active_hand()
        intro = f"Dealer {self.round_state.dealer_upcard.display}. Hand {self.round_state.active_hand_index + 1}: {hand.label()}."
        if is_blackjack(hand.cards):
            return f"{intro} Blackjack."
        return f"{intro} {recommendation.summary}"
