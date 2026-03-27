import unittest

from bjcalc.cards import CardRank
from bjcalc.parser import Command
from bjcalc.state import BlackjackController, Phase
from bjcalc.strategy import RulesPreset


def build_controller() -> BlackjackController:
    return BlackjackController(RulesPreset())


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

    def test_next_hand_resets(self) -> None:
        controller = build_controller()
        controller.arm()
        controller.handle_cards([CardRank.THREE, CardRank.FIVE, CardRank.SIX])
        reply = controller.handle_command(Command.NEXT_HAND)
        self.assertEqual(controller.phase, Phase.IDLE)
        self.assertEqual(reply.spoken, "Ready for the next hand.")


if __name__ == "__main__":
    unittest.main()
