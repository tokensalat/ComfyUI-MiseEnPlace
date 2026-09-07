from ._pattern_sweep import parse_pattern, sweep_total


class PatternSweepConfig:
    """Parses `pattern` and reports how many steps the sweep takes (length + pattern length),
    so a loop driving PatternSweep.index_in can size itself without re-deriving that math.
    Wire this node's pattern/length/identity/mirror outputs into PatternSweep's matching
    inputs, and total into whatever bounds your index loop - index_in itself connects straight
    from the loop to PatternSweep, not through here."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "pattern": (
                    "STRING",
                    {"default": "2,3", "tooltip": "Comma/semicolon separated values, entered one per step."},
                ),
                "length": ("INT", {"default": 3, "min": 1, "max": 4096}),
                "identity": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": -1e9,
                        "max": 1e9,
                        "step": 0.01,
                        "tooltip": "Fill/no-op value everywhere the pattern hasn't reached yet or has already passed.",
                    },
                ),
                "mirror": ("BOOLEAN", {"default": False, "tooltip": "Reverse the order the pattern's values enter."}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT", "BOOLEAN", "INT")
    RETURN_NAMES = ("pattern", "length", "identity", "mirror", "total")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Loopers"

    def run(self, pattern, length, identity, mirror):
        total = sweep_total(parse_pattern(pattern), length)
        return (pattern, length, identity, mirror, total)


NODE_CLASS_MAPPINGS = {"PatternSweepConfig": PatternSweepConfig}
NODE_DISPLAY_NAME_MAPPINGS = {"PatternSweepConfig": "Pattern Sweep Config"}
