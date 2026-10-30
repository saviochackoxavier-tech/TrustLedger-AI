"""
TrustLedger AI — Input Sanitization
===================================
Strict, dependency-free sanitizers applied to EVERY user-submitted string
(dispute evidence, delivery artifacts, milestone titles/descriptions, refs)
before persistence or AI consumption.

Layers:
1. Tag stripping — stdlib HTMLParser drops every HTML tag and drops the
   entire content of <script>/<style> blocks (allowlist of tags: ZERO).
2. Control/bidi stripping — removes C0 controls and Unicode bidi/zero-width
   chars used in prompt-override and invisible-character attacks.
3. Whitespace normalization + hard length caps.
4. Output context is Django's autoescape (all templates), plus `|escapejs`
   for inline JS — stored text is plain data, never markup.
"""

import html.parser
import re

# Unicode bidi / zero-width / soft-hyphen characters (prompt-injection aids)
_BIDI_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\u00ad]"
)
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

_DROP_CONTENT_TAGS = {"script", "style"}


class _TextExtractor(html.parser.HTMLParser):
    """Keeps text nodes only; silently discards tags and dangerous content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT_TAGS:
            self._dropping += 1

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT_TAGS and self._dropping:
            self._dropping -= 1

    def handle_data(self, data):
        if not self._dropping:
            self.chunks.append(data)


def sanitize_text(value: str, max_length: int = 8000) -> str:
    """Reduce arbitrary user text to safe plain text, capped at max_length."""
    if not isinstance(value, str):
        return ""
    extractor = _TextExtractor()
    extractor.feed(value[: max_length * 4])  # bounded feed; hard cap below too
    extractor.close()
    text = "".join(extractor.chunks)
    text = _BIDI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()[:max_length]


def sanitize_ref(value: str, max_length: int = 120) -> str:
    """Whitelist PayPal party refs (payer ID or email): word chars, @, . + -."""
    value = sanitize_text(value, max_length)
    return value if re.fullmatch(r"[\w.@+-]{2,120}", value) else ""
