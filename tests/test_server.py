"""Expected disconnects from canceled frontend polling must not retry a response."""
import unittest
from unittest.mock import Mock

import server


class ResponseTests(unittest.TestCase):
    def test_canceled_response_is_handled_during_headers_or_body(self):
        for exception in (BrokenPipeError, ConnectionResetError):
            for stage in ("headers", "body"):
                with self.subTest(exception=exception, stage=stage):
                    handler = object.__new__(server.Handler)
                    handler.send_response = Mock()
                    handler.send_header = Mock()
                    handler.end_headers = Mock(side_effect=exception() if stage == "headers" else None)
                    handler.wfile = Mock()
                    if stage == "body":
                        handler.wfile.write.side_effect = exception()
                    handler.send({"project": "test"})
                    handler.send_response.assert_called_once_with(200)


if __name__ == "__main__":
    unittest.main()
