import unittest

from bj_helper.cards import CardRank
from bj_helper.parser import Command, parse_cards_phrase, parse_command_phrase


class ParserTests(unittest.TestCase):
    def test_parse_opening_cards(self) -> None:
        result = parse_cards_phrase("five ace seven", expected_count=3)
        self.assertIsNone(result.error)
        self.assertEqual(result.cards, [CardRank.FIVE, CardRank.ACE, CardRank.SEVEN])

    def test_parse_cards_rejects_unknown_token(self) -> None:
        result = parse_cards_phrase("five banana seven", expected_count=3)
        self.assertEqual(result.error, "Unrecognized card word: banana")

    def test_parse_command_alias(self) -> None:
        result = parse_command_phrase("next hand")
        self.assertEqual(result.command, Command.NEXT_HAND)

    def test_parse_short_next_alias(self) -> None:
        result = parse_command_phrase("next")
        self.assertEqual(result.command, Command.NEXT_HAND)


if __name__ == "__main__":
    unittest.main()
