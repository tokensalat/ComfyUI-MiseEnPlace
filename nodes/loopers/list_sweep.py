from ..formatting._escapes import unescape


class ListSweep:
    """Picks one item at a time from a delimited list, driven by index_in - the same
    index_in/total/status pattern as SamplerSchedulerLooper and PatternSweep, but for an
    arbitrary list of strings (prompts, LoRA names, file paths, ...) instead of a fixed
    combination format or a numeric pattern. Wire index_in to an INT primitive set to
    "increment" and total to that primitive's max."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "items": (
                    "STRING",
                    {"default": "a,b,c", "multiline": True, "tooltip": "List of items, split by delimiter."},
                ),
                "delimiter": (
                    "STRING",
                    {"default": ",", "tooltip": "Splits 'items'. \\n, \\t and \\\\ are interpreted."},
                ),
                "index_in": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("item", "total", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Loopers"

    def run(self, items, delimiter, index_in):
        delim = unescape(delimiter) or ","
        parsed = [tok.strip() for tok in items.split(delim) if tok.strip()]
        total = len(parsed)

        if total == 0:
            status = "[0 / 0] (no items)"
            print(f"[ListSweep] {status}")
            return ("", 0, status)

        k = max(0, min(index_in, total - 1))
        item = parsed[k]
        status = f"[{k + 1} / {total}] {item}"
        print(f"[ListSweep] {status}")
        return (item, total, status)


NODE_CLASS_MAPPINGS = {"ListSweep": ListSweep}
NODE_DISPLAY_NAME_MAPPINGS = {"ListSweep": "List Sweep"}
