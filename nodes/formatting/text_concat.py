from comfy_api.latest import io

# Matches MAX_ITEMS in ../bundling/bundler.py - same Autogrow mechanic, so the
# same ceiling.
MAX_PARTS = 32

# Widgets are single-line, so a separator of "\n" has to be typed as an escape
# and turned back into the real character here. Backslash last, or it would
# re-escape the ones already substituted.
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


class TextConcat(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        template = io.Autogrow.TemplatePrefix(
            input=io.String.Input("text"),
            prefix="text",
            min=1,
            max=MAX_PARTS,
        )
        return io.Schema(
            node_id="TextConcat",
            display_name="Text Concat",
            category="MiseEnPlace/Formatting",
            description=(
                "Joins any number of text inputs into one string. Connect parts in order and a "
                "new slot appears automatically, the same way Bundler grows. The separator "
                "understands \\n, \\t and \\\\ escapes; empty parts are skipped by default so "
                "an unused slot doesn't leave a dangling separator behind."
            ),
            inputs=[
                io.String.Input(
                    "separator",
                    optional=True,
                    default="\\n\\n",
                    tooltip="Placed between parts. \\n, \\t and \\\\ are interpreted; leave blank to join with nothing.",
                ),
                io.Boolean.Input(
                    "skip_empty",
                    optional=True,
                    default=True,
                    tooltip="Leave out parts that are empty (or whitespace only) instead of joining them and doubling up separators.",
                ),
                io.Boolean.Input(
                    "strip",
                    optional=True,
                    default=False,
                    tooltip="Trim leading and trailing whitespace from each part before joining.",
                ),
                io.Autogrow.Input("parts", template=template),
            ],
            outputs=[
                io.String.Output(display_name="text"),
                io.Int.Output(display_name="part_count"),
            ],
        )

    @classmethod
    def execute(
        cls,
        parts: io.Autogrow.Type = None,
        separator: str = "\\n\\n",
        skip_empty: bool = True,
        strip: bool = False,
    ) -> io.NodeOutput:
        values = []
        for value in (parts or {}).values():
            text = "" if value is None else str(value)
            if strip:
                text = text.strip()
            if skip_empty and not text.strip():
                continue
            values.append(text)
        return io.NodeOutput(unescape(separator or "").join(values), len(values))


NODE_CLASS_MAPPINGS = {"TextConcat": TextConcat}

NODE_DISPLAY_NAME_MAPPINGS = {"TextConcat": "Text Concat"}
