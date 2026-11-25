import threading
import unittest
from unittest.mock import Mock
import sender


class SenderTests(unittest.TestCase):
    def test_message_and_permissions(self):
        post = Mock(return_value=Mock(status_code=200, ok=True))
        report = Mock()
        sender.run("123", "example", "Offer\nPrice", "60", False, threading.Event(), report, post)
        args = post.call_args.kwargs
        self.assertEqual(args["json"], {"content": "Offer\nPrice", "allowed_mentions": {"parse": []}})
        self.assertEqual(args["headers"]["Authorization"], "Bot example")
        self.assertIn("Sent at", report.call_args.args[0])

    def test_rate_limit_wait_can_be_cancelled(self):
        stop = threading.Event()
        post = Mock(return_value=Mock(status_code=429, json=lambda: {"retry_after": 60}))
        sender.run("123", "example", "Offer", "60", True, stop, lambda _: stop.set(), post)
        post.assert_called_once()

    def test_validation(self):
        args = ["12345678901234567", "example", "Offer", "1"]
        sender.validate(*args)
        for i, bad in enumerate(["abc", "", " " * 10, "0"]):
            with self.subTest(i=i), self.assertRaises(ValueError):
                sender.validate(*args[:i], bad, *args[i + 1:])
