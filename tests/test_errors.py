"""scripts/errors.py: which wrapper output counts as an account-type error."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from errors import account_error  # noqa: E402


class AccountErrorTest(unittest.TestCase):
    def test_caught_and_ignored(self):
        caught = {
            "agy eligibility": "agy-run: Your account is not eligible for Antigravity in this region",
            "glm 401": "glm-run: the worker reported failure (subtype=success, "
                       "api_error_status=401).",
            "429 rate limit": "error: 429 Too Many Requests - rate limit exceeded",
            "agy location": "agy-run: FAILED_PRECONDITION (code 400): User location is not "
                            "supported for the API use.",
        }
        for name, line in caught.items():
            with self.subTest(caught=name):
                text = "some answer text\n" + line + "\n"
                self.assertEqual(account_error(text), line.strip())
        ignored = "The quota check in billing.py is wrong: it never resets the rate limit.\n"
        self.assertIsNone(account_error(ignored))


if __name__ == "__main__":
    unittest.main()
