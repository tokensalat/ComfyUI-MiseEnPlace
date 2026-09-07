# Widgets are single-line, so a separator/delimiter of "\n" has to be typed as an escape
# and turned back into the real character here. Backslash last, or it would re-escape
# the ones already substituted.
ESCAPES = (
    ("\\n", "\n"),
    ("\\t", "\t"),
    ("\\r", "\r"),
    ("\\\\", "\\"),
)


def unescape(text: str) -> str:
    for token, char in ESCAPES:
        text = text.replace(token, char)
    return text
