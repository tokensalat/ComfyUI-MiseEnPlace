"""
Shared reply-extraction helper for the llama-cpp nodes.

Both LlamaCppClient and LlamaCppChatSession pull a payload out of the model's
reply with the same regex and the same rules, so the pattern spec and the
matching live here rather than being duplicated. Prefixed with "_" so the
package's node auto-discovery (see ../../__init__.py) skips it.
"""

import re

EXTRACT_PATTERN_DEFAULT = r"<prompt>(.*?)</prompt>"
EXTRACT_PATTERN_TOOLTIP = (
    "Regex applied to the reply. Matches from the rear (last occurrence wins). First capture "
    "group (or the whole match if the pattern has none) becomes the 'extracted' output. Leave "
    "blank to skip extraction."
)


def extract_pattern_input(**overrides):
    options = {"default": EXTRACT_PATTERN_DEFAULT, "tooltip": EXTRACT_PATTERN_TOOLTIP}
    options.update(overrides)
    return ("STRING", options)


def extract_from_reply(text, pattern, log_prefix=""):
    """The last match of `pattern` in `text`, or "" if there isn't one.

    Matching runs from the rear because a reply can contain more than one
    occurrence - a model that second-guesses itself emits the tag twice - and
    the final one is the answer it settled on. A bad pattern is reported and
    treated as no match rather than raised: a typo in a regex widget should
    not fail the whole queue.
    """
    if not pattern:
        return ""
    try:
        matches = list(re.finditer(pattern, text or "", re.DOTALL | re.IGNORECASE))
    except re.error as e:
        print(f"{log_prefix}invalid extract_pattern: {e}")
        return ""
    if not matches:
        print(f"{log_prefix}extract_pattern found no match")
        return ""
    match = matches[-1]
    return match.group(1) if match.groups() else match.group(0)
