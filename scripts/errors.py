"""Recognise an account, eligibility, quota, auth or region error in a wrapper's output.

Only lines the wrappers or the CLIs print themselves are considered (`glm-run:`, `agy-run:`,
`error:`, `api_error...`), so a model answer that mentions "quota" is not mistaken for one.
"""
import re

SOURCE = re.compile(r"^\s*(glm-run:|agy-run:|error:|\[?api_error|.*api_error_status=)", re.I)
ACCOUNT = re.compile(
    r"eligib|not available in your location|unsupported (country|region)|region"
    r"|location is not supported|FAILED_PRECONDITION"
    r"|quota|rate.?limit|insufficient (balance|credit|quota)|billing|payment"
    r"|unauthori[sz]ed|forbidden|token expired|expired or incorrect|invalid (api )?key"
    r"|api_error_status=(401|402|403|429)",
    re.I,
)


def account_error(text):
    """The last line of `text` that reports an account-type error, or None."""
    hits = [line.strip() for line in text.splitlines() if SOURCE.search(line) and ACCOUNT.search(line)]
    return hits[-1][:300] if hits else None
