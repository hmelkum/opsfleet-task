import pytest

from src.core.pii.masking import MAX_PATTERN_CHARS, StreamingMasker, mask_pii


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Contact john.doe@example.com today", "email"),
        ("Call +1 555 123 4567", "phone"),
        ("Call (555) 123-4567", "phone"),
        ("Call 555-123-4567", "phone"),
        ("Call +44 20 7946 0958", "phone"),
        ("Card 4111 1111 1111 1111 on file", "card"),
        ("Card 4111-1111-1111-1111", "card"),
    ],
)
def test_masks_pii(text, kind):
    masked, counts = mask_pii(text)
    assert f"[{kind} removed]" in masked and counts[kind] == 1


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was 4260905.0 USD in the Men department.",
        "The query scanned 1073741824 bytes.",
        "Orders from 2026-10-15 to 2026-10-31.",
        "Top customer is user_id 12345 with $1,234,567.89.",
        "| 2026-09 | 125,004 | 3,838,905 |",
        "Growth of 12.5% (from 1234567890123 to 1234567890999).",
        "SKU 4111111111111112 is not a valid card.",
    ],
)
def test_keeps_analytics_numbers(text):
    assert mask_pii(text) == (text, {})


def test_streaming_masks_values_split_across_chunks():
    masker = StreamingMasker()
    text = "Please write to jane." + "x" * 3 + "@exam" + "ple.com for details. " + "Then more text follows here. " * 5
    chunks = [text[i:i + 7] for i in range(0, len(text), 7)]
    released = "".join(masker.feed(c) for c in chunks) + masker.flush()
    assert "jane" not in released and "[email removed]" in released
    assert released == mask_pii(text)[0]
    assert masker.counts["email"] == 1


def test_streaming_releases_text_with_bounded_delay():
    masker = StreamingMasker()
    released = masker.feed("word " * 40)
    assert released and len("word " * 40) - len(released) <= MAX_PATTERN_CHARS + 5
