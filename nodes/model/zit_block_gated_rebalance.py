# No learned per-block signal exists for Z-Image (its AdaLN gate is computed dynamically
# from the timestep+caption embedding at runtime, not a static checkpoint tensor - unlike
# Krea2's txtfusion.projector.weight). This 3-way split of the 30 blocks instead mirrors the
# convention used by ShootTheSound/comfyUI-Realtime-Lora's ZImageModelLayerEditor
# (model_layer_analyzer.py, ARCH_CONFIGS["ZIMAGE"]) - a generic early/mid/late heuristic
# (same template that repo applies to SDXL/FLUX too), not something measured for Z-Image itself.
ZIT_GROUPS = [
    ("early", list(range(0, 10))),   # "structure"
    ("mid", list(range(10, 20))),    # "features"
    ("late", list(range(20, 30))),   # "details"
]


class ZitBlockGatedRebalance:
    """Per-block gain control for Z-Image's DiT transformer blocks.

    Z-Image's text conditioning is a single hidden-state tap (see comfy/text_encoders/z_image.py),
    unlike Krea2's 12-layer stack — there's nothing to gate on the CONDITIONING side. Instead this
    patches the MODEL, scaling each block's own residual contribution via ComfyUI's
    "double_block" patch hook (comfy/ldm/lumina/model.py): block_out = block_in + weight * (block_out - block_in).
    weight=1 -> unchanged, weight=0 -> skip the block, weight>1 -> amplify it.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "early_weights_10": (
                    "STRING",
                    {"default": "1,1,1,1,1,1,1,1,1,1", "tooltip": "one per block, blocks 0-9 (structure)"},
                ),
                "mid_weights_10": (
                    "STRING",
                    {"default": "1,1,1,1,1,1,1,1,1,1", "tooltip": "one per block, blocks 10-19 (features)"},
                ),
                "late_weights_10": (
                    "STRING",
                    {"default": "1,1,1,1,1,1,1,1,1,1", "tooltip": "one per block, blocks 20-29 (details)"},
                ),
                "multiplier": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": -1e9,
                        "max": 1e9,
                        "step": 0.01,
                        "tooltip": "Flat gain applied on top of every block's effective weight, after crossover/overlap blending.",
                    },
                ),
                "crossover": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
                "overlap": (
                    "FLOAT",
                    {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01},
                ),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Model"

    def _parse_weights(self, s):
        """Comma/semicolon separated weights."""
        weights = []
        try:
            for tok in (x.strip() for x in s.replace(";", ",").split(",")):
                if not tok:
                    continue
                weights.append(float(tok))
        except ValueError:
            return []
        return weights

    def _blend_weights(self, weights, crossover, overlap):
        """Same crossover/overlap smooth-step gating as Krea2GatedRebalance, applied by block position."""
        n = len(weights)
        if n == 0:
            return weights

        blended = []
        for i, w in enumerate(weights):
            pos = i / max(n - 1, 1)

            if pos >= crossover:
                blend = 1.0
            elif overlap <= 0.0 or pos < crossover - overlap:
                blend = 0.0
            else:
                t = (pos - (crossover - overlap)) / overlap
                t = max(0.0, min(1.0, t))
                blend = t * t * (3.0 - 2.0 * t)  # smoothstep

            blended.append(1.0 + blend * (w - 1.0))

        return blended

    def run(self, model, early_weights_10, mid_weights_10, late_weights_10, multiplier, crossover, overlap):
        group_strings = [early_weights_10, mid_weights_10, late_weights_10]
        weights = []
        for (name, blocks), group_s in zip(ZIT_GROUPS, group_strings):
            group_weights = self._parse_weights(group_s)
            if len(group_weights) != len(blocks):
                raise ValueError(
                    f"[ZitBlockGatedRebalance] '{name}_weights' needs exactly {len(blocks)} value(s) "
                    f"(blocks {blocks[0]}-{blocks[-1]}) - got {len(group_weights)}"
                )
            weights.extend(group_weights)

        weights = self._blend_weights(weights, crossover, overlap)
        weights = [w * multiplier for w in weights]
        print(f"[ZitBlockGatedRebalance] effective per-block weights: {[round(w, 3) for w in weights]}, multiplier={multiplier}")

        def double_block_patch(args):
            i = args["block_index"]
            w = weights[i] if i < len(weights) else 1.0
            if w == 1.0 or "img" not in args or "img_input" not in args:
                return {}
            return {"img": args["img_input"] + w * (args["img"] - args["img_input"])}

        m = model.clone()
        m.set_model_double_block_patch(double_block_patch)
        return (m,)


NODE_CLASS_MAPPINGS = {"ZitBlockGatedRebalance": ZitBlockGatedRebalance}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZitBlockGatedRebalance": "ZiT Block Gated Rebalance"
}
