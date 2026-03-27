import unittest

from evdev import ecodes

from bjcalc.hotkey_helper import parse_shortcut


class HotkeyHelperTests(unittest.TestCase):
    def test_parse_shortcut_alt_z(self) -> None:
        modifiers, target = parse_shortcut("Alt+Z")
        self.assertEqual(target, ecodes.KEY_Z)
        self.assertEqual(len(modifiers), 1)
        self.assertIn(ecodes.KEY_LEFTALT, modifiers[0])

    def test_parse_shortcut_supports_shift_and_digits(self) -> None:
        modifiers, target = parse_shortcut("Ctrl+Shift+7")
        self.assertEqual(target, ecodes.KEY_7)
        self.assertEqual(len(modifiers), 2)
        self.assertTrue(any(ecodes.KEY_LEFTSHIFT in group for group in modifiers))

    def test_parse_shortcut_rejects_missing_modifier(self) -> None:
        with self.assertRaises(ValueError):
            parse_shortcut("B")


if __name__ == "__main__":
    unittest.main()
