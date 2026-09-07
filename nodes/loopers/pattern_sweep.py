from ._pattern_sweep import parse_pattern, sweep_values


class PatternSweep:
    """Slides `pattern` across a `length`-long array of `identity`, one value per index_in step -
    like a shift register: pattern's values enter one at a time from the front and push earlier
    ones right. E.g. pattern="2,3", length=3, identity=1: index_in 0..4 gives
    1,1,1 / 2,1,1 / 3,2,1 / 1,3,2 / 1,1,3. mirror reverses the entry order (pattern read back to
    front). Takes pattern/length/identity/mirror directly (defaults let it stand alone) or wired
    from PatternSweepConfig, while index_in connects straight from your loop counter - the two
    nodes are split so index_in never has to round-trip through the config node. Wire the STRING
    output into any of this repo's comma-separated weight inputs (ZitBlockGatedRebalance's
    early/mid/late_weights_10, Krea2GatedRebalance's *_weights, ZitConditioningRebalance's
    per_channel_weights, ...) to sweep a change through it one position at a time."""

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
                "index_in": ("INT", {"default": 0, "min": 0}),
                "mirror": ("BOOLEAN", {"default": False, "tooltip": "Reverse the order the pattern's values enter."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("weights", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Loopers"

    def run(self, pattern, length, identity, index_in, mirror):
        values, total, k = sweep_values(parse_pattern(pattern), length, identity, index_in, mirror)
        weights = ",".join(f"{v:g}" for v in values)
        status = f"[{k + 1} / {total}] {weights}"
        print(f"[PatternSweep] {status}")
        return (weights, status)


NODE_CLASS_MAPPINGS = {"PatternSweep": PatternSweep}
NODE_DISPLAY_NAME_MAPPINGS = {"PatternSweep": "Pattern Sweep"}
