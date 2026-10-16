"""
Output masking: the last of three PII layers.

PII cannot be queried (the virtual tables have no PII columns) and is never
logged; this catches what is left, such as an identifier the model invented or
echoed from the user's own message. Regexes are brittle on their own, which is
why this is the backstop, not the defense.
"""
import re
from collections import Counter

# Strict on purpose: answers are full of large numbers (revenue, bytes, ids) that must survive.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # 13-19 digits, optionally grouped by spaces or dashes; must also pass the Luhn check
    "card": re.compile(r"(?<![\w.])\d(?:[ -]?\d){12,18}(?![\w.])"),
    # international (+country code) or separated national format, e.g. +1 555 123 4567, (555) 123-4567
    "phone": re.compile(
        r"(?<![\w+])(?:\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){2,4}"
        r"|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4})(?![\w])"
    ),
}

_PLACEHOLDERS = {name: f"[{name} removed]" for name in _PATTERNS}


def _luhn_valid(value: str) -> bool:
    digits = [int(d) for d in value if d.isdigit()]
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


# Longest text a pattern can span; a streamed tail this long is held back until it is complete.
MAX_PATTERN_CHARS = 64


def mask_pii(text: str, *, complete: bool = True) -> tuple[str, Counter[str]]:
    """Returns the masked text and how many values of each kind were masked.

    With ``complete=False`` the text may still grow, so a match touching its end is left as is.
    """
    counts: Counter[str] = Counter()

    def replace(name: str):
        def _replace(match: re.Match[str]) -> str:
            if not complete and match.end() == len(match.string):
                return match.group(0)
            if name == "card" and not _luhn_valid(match.group(0)):
                return match.group(0)
            counts[name] += 1
            return _PLACEHOLDERS[name]
        return _replace

    for name, pattern in _PATTERNS.items():
        text = pattern.sub(replace(name), text)
    return text, counts


class StreamingMasker:
    """Masks a stream of text chunks, even when a value is split across chunks.

    The buffer is always masked as a whole, and the last ``MAX_PATTERN_CHARS``
    are held back, so a value that is still incomplete is never released.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.counts: Counter[str] = Counter()

    def feed(self, chunk: str) -> str:
        self._buffer, counts = mask_pii(self._buffer + chunk, complete=False)
        self.counts.update(counts)
        cut = len(self._buffer) - MAX_PATTERN_CHARS
        if cut <= 0:
            return ""
        # Release only up to a whitespace boundary, so a held-back value is never split.
        boundary = max(self._buffer.rfind(" ", 0, cut), self._buffer.rfind("\n", 0, cut))
        if boundary <= 0:
            return ""
        released, self._buffer = self._buffer[:boundary], self._buffer[boundary:]
        return released

    def flush(self) -> str:
        released, counts = mask_pii(self._buffer)
        self.counts.update(counts)
        self._buffer = ""
        return released
