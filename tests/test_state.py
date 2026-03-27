import unittest

from bj_helper.cards import CardRank
from bj_helper.parser import Command
from bj_helper.state import BlackjackController, HandState, Phase, RoundState
from bj_helper.strategy import RulesPreset


def build_controller(**rules_kwargs) -> BlackjackController:
    return BlackjackController(RulesPreset(**rules_kwargs))


class StateTests(unittest.TestCase):
    def test_opening_round_recommends(self) -> None:
        controller = build_controller()
        controller.arm()
        reply = controller.handle_cards([CardRank.FIVE, CardRank.ACE, CardRank.SEVEN])
        self.assertEqual(controller.phase, Phase.AWAIT_CARD)
        self.assertEqual(controller.pending_action.name, "DOUBLE")
        self.assertEqual(reply.spoken, "Double.")
        self.assertIn("Dealer 5.", reply.display or "")

    def test_hit_then_draw_auto_advances_to_next_recommendation(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.TEN, CardRank.FIVE, CardRank.FIVE])
        self.assertEqual(controller.phase, Phase.AWAIT_CARD)
        reply = controller.handle_cards([CardRank.TWO])
        self.assertEqual(controller.phase, Phase.AWAIT_CARD)
        self.assertEqual(reply.spoken, "Hit.")
        self.assertIn("Hand 1:", reply.display or "")

    def test_split_flow_auto_starts_split(self) -> None:
        controller = build_controller()
        controller.arm()
        reply = controller.handle_cards([CardRank.SIX, CardRank.EIGHT, CardRank.EIGHT])
        self.assertEqual(controller.phase, Phase.AWAIT_SPLIT_CARD)
        self.assertEqual(reply.spoken, "Split.")
        controller.handle_cards([CardRank.THREE])
        reply = controller.handle_cards([CardRank.FOUR])
        self.assertEqual(controller.phase, Phase.AWAIT_CARD)
        self.assertEqual(reply.spoken, "Double.")
        self.assertIn("Hand 1:", reply.display or "")

    def test_split_aces_lock_after_one_replacement_each(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.SIX, CardRank.ACE, CardRank.ACE])
        controller.handle_cards([CardRank.FIVE])
        reply = controller.handle_cards([CardRank.FOUR])

        self.assertEqual(controller.phase, Phase.ROUND_COMPLETE)
        self.assertIsNone(controller.pending_action)
        self.assertEqual(reply.spoken, "Stand.")
        self.assertTrue(all(hand.finished for hand in controller.round_state.hands))

    def test_split_aces_do_not_resplit_on_ace_replacement(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.SIX, CardRank.ACE, CardRank.ACE])
        controller.handle_cards([CardRank.ACE])
        reply = controller.handle_cards([CardRank.NINE])

        self.assertEqual(controller.phase, Phase.ROUND_COMPLETE)
        self.assertEqual(len(controller.round_state.hands), 2)
        self.assertEqual(reply.spoken, "Stand.")
        self.assertTrue(all(hand.finished for hand in controller.round_state.hands))

    def test_split_is_illegal_once_max_split_hands_is_reached(self) -> None:
        controller = build_controller(max_split_hands=3)
        controller.round_state = RoundState(
            dealer_upcard=CardRank.SIX,
            hands=[
                HandState(cards=[CardRank.EIGHT, CardRank.EIGHT]),
                HandState(cards=[CardRank.NINE, CardRank.TWO], finished=True),
                HandState(cards=[CardRank.THREE, CardRank.THREE], finished=True),
            ],
        )

        recommendation = controller._current_recommendation()

        self.assertEqual(recommendation.action.name, "STAND")
        self.assertEqual(len(controller.round_state.hands), 3)

    def test_split_is_still_allowed_below_max_split_hands(self) -> None:
        controller = build_controller(max_split_hands=3)
        controller.round_state = RoundState(
            dealer_upcard=CardRank.SIX,
            hands=[
                HandState(cards=[CardRank.EIGHT, CardRank.EIGHT]),
                HandState(cards=[CardRank.NINE, CardRank.TWO], finished=True),
            ],
        )

        recommendation = controller._current_recommendation()

        self.assertEqual(recommendation.action.name, "SPLIT")

    def test_next_hand_resets(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.THREE, CardRank.FIVE, CardRank.SIX])
        reply = controller.handle_command(Command.NEXT_HAND)
        self.assertEqual(controller.phase, Phase.IDLE)
        self.assertEqual(reply.spoken, "Ready for the next hand.")

    def test_repeat_without_any_advice_reports_none(self) -> None:
        controller = build_controller()
        controller.arm()

        reply = controller.handle_command(Command.REPEAT)

        self.assertEqual(reply.spoken, "No advice to repeat.")

    def test_repeat_replays_last_advice_not_last_prompt(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.FIVE, CardRank.ACE, CardRank.SEVEN])

        reply = controller.handle_command(Command.REPEAT)

        self.assertEqual(reply.spoken, "Double.")

    def test_next_hand_clears_repeatable_advice(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.FIVE, CardRank.ACE, CardRank.SEVEN])
        controller.handle_command(Command.NEXT_HAND)

        reply = controller.handle_command(Command.REPEAT)

        self.assertEqual(reply.spoken, "No advice to repeat.")


if __name__ == "__main__":
    unittest.main()
