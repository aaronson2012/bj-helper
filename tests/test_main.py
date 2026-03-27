import unittest
from io import StringIO
from unittest.mock import patch

import bj_helper.__main__ as main_module


class MainTests(unittest.TestCase):
    def test_main_dispatches_start_listening_command(self) -> None:
        with patch.object(main_module, "send_start_listening", return_value=True) as send_start_listening:
            result = main_module.main(["start-listening"])

        self.assertEqual(result, 0)
        send_start_listening.assert_called_once_with()

    def test_main_reports_running_instance(self) -> None:
        with patch.object(main_module, "ping_server", return_value=True) as ping_server:
            result = main_module.main(["is-running"])

        self.assertEqual(result, 0)
        ping_server.assert_called_once_with()

    def test_main_rejects_unknown_arguments(self) -> None:
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            result = main_module.main(["unknown"])

        self.assertEqual(result, 2)
        self.assertIn("Usage:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
