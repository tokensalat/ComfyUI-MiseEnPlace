import json


class JsonArrayToLines:
    """Converts a JSON array into a newline-separated string, one element per line - for
    feeding a JSON list (e.g. an LLM's structured output) into anything that wants
    newline-delimited text. Non-string elements are re-serialized with json.dumps so
    objects/numbers/booleans still show up as one line each."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "json_array": ("STRING", {"default": "[]", "multiline": True}),
                "skip": (
                    "INT",
                    {"default": 0, "min": 0, "tooltip": "Number of leading elements to leave out."},
                ),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("lines", "count")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Formatting"

    def run(self, json_array, skip):
        try:
            items = json.loads(json_array)
        except json.JSONDecodeError as e:
            print(f"[JsonArrayToLines] invalid JSON: {e}")
            return ("", 0)

        if not isinstance(items, list):
            print(f"[JsonArrayToLines] expected a JSON array, got {type(items).__name__}")
            return ("", 0)

        lines = [item if isinstance(item, str) else json.dumps(item) for item in items[skip:]]
        return ("\n".join(lines), len(lines))


NODE_CLASS_MAPPINGS = {"JsonArrayToLines": JsonArrayToLines}
NODE_DISPLAY_NAME_MAPPINGS = {"JsonArrayToLines": "JSON Array to Lines"}
