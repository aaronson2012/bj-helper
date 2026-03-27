import unittest

from bj_helper.cards import CardRank
from bj_helper.strategy import Action, BasicStrategyEngine, RulesPreset


def build_engine(**kwargs) -> BasicStrategyEngine:
    return BasicStrategyEngine(RulesPreset(**kwargs))


class StrategyTests(unittest.TestCase):
    def test_hard_sixteen_vs_ten_surrenders(self) -> None:
        engine = build_engine(surrender="late")
        decision = engine.recommend(
            [CardRank.NINE, CardRank.SEVEN],
            CardRank.TEN,
            can_double=True,
            can_split=False,
            can_surrender=True,
        )
        self.assertEqual(decision.action, Action.SURRENDER)

    def test_pair_of_eights_splits(self) -> None:
        engine = build_engine()
        decision = engine.recommend(
            [CardRank.EIGHT, CardRank.EIGHT],
            CardRank.TEN,
            can_double=True,
            can_split=True,
            can_surrender=False,
        )
        self.assertEqual(decision.action, Action.SPLIT)

    def test_soft_eighteen_vs_nine_hits(self) -> None:
        engine = build_engine()
        decision = engine.recommend(
            [CardRank.ACE, CardRank.SEVEN],
            CardRank.NINE,
            can_double=True,
            can_split=False,
            can_surrender=False,
        )
        self.assertEqual(decision.action, Action.HIT)

    def test_hard_eleven_doubles(self) -> None:
        engine = build_engine()
        decision = engine.recommend(
            [CardRank.FIVE, CardRank.SIX],
            CardRank.SEVEN,
            can_double=True,
            can_split=False,
            can_surrender=False,
        )
        self.assertEqual(decision.action, Action.DOUBLE)


if __name__ == "__main__":
    unittest.main()
