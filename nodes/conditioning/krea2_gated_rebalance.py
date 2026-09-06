import torch


KREA2_N_TAPS = 12
KREA2_HIDDEN_DIM = 2560
KREA2_FEATURE_DIM = KREA2_N_TAPS * KREA2_HIDDEN_DIM  # 30720


# Krea2's 12 taps read hidden_states[2,5,8,11,14,17,20,23,26,29,32,35] of Qwen3-VL-4B.
# Grouped by where the model's own learned tap-combination weights (txtfusion.projector)
# actually differ: taps 0-6 sit near baseline, taps 7-10 are the strongly-weighted
# (large-magnitude, negative) cluster, tap 11 is the last one before the DiT.
KREA2_GROUPS = [
    ("early", [2, 5, 8, 11, 14, 17, 20]),
    ("detail", [23, 26, 29, 32]),
    ("refinement", [35]),
]


class Krea2GatedRebalance:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "early_weights_7": (
                    "STRING",
                    {"default": "1,1,1,1,1,1,1", "tooltip": "one per tap, layers 2,5,8,11,14,17,20 of Qwen3-VL-4B"},
                ),
                "detail_weights_4": (
                    "STRING",
                    {"default": "2.5,5,1.1,4", "tooltip": "one per tap, layers 23,26,29,32 of Qwen3-VL-4B"},
                ),
                "refinement_weights_1": (
                    "STRING",
                    {"default": "1", "tooltip": "the last tap, layer 35 of Qwen3-VL-4B"},
                ),
                "multiplier": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": -1e9,
                        "max": 1e9,
                        "step": 0.01,
                        "tooltip": "Flat gain applied on top of the per-tap weights - Krea2's raw conditioning is small in magnitude, so you'll likely want this >1.",
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

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Conditioning"

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
        """Apply crossover/overlap smooth-step to each tap's weight.

        crossover is the tap position (0–1) where the weights are FULLY applied.
        overlap is the ramp width BEFORE that point.
        Transition zone: [crossover - overlap, crossover].

        crossover=0 → all taps at full weight (same as reference node, no gating).
        crossover=0.5, overlap=0 → hard cutoff: first half unscaled, second half scaled.
        crossover=0.5, overlap=0.2 → smooth ramp from tap 30% to tap 50%.
        """
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

    def _scale_tensor(self, t, weights, multiplier):
        flat = t.shape[-1]
        n = len(weights)
        if flat % n != 0:
            raise ValueError(
                f"[Krea2GatedRebalance] tensor last dim {flat} is not divisible by "
                f"{n} per-layer weights; expected {KREA2_N_TAPS} weights for a "
                f"{KREA2_FEATURE_DIM}-dim Krea2 conditioning tensor"
            )
        tap_dim = flat // n
        orig_dtype = t.dtype
        t = t.float()
        t = t.view(*t.shape[:-1], n, tap_dim)
        gains = torch.tensor(weights, dtype=t.dtype, device=t.device)
        gains = gains.view(*([1] * (t.dim() - 2)), n, 1)
        t = t * gains
        t = t.view(*t.shape[:-2], flat)
        return t.to(orig_dtype) * multiplier

    def _apply(self, structure, weights, multiplier):
        if isinstance(structure, list):
            out = []
            for item in structure:
                if (isinstance(item, (list, tuple)) and len(item) == 2
                        and isinstance(item[0], torch.Tensor)
                        and isinstance(item[1], dict)):
                    cond_t, extras = item
                    out.append([self._scale_tensor(cond_t, weights, multiplier), dict(extras)])
                else:
                    out.append(self._apply(item, weights, multiplier))
            return out
        if isinstance(structure, torch.Tensor):
            return self._scale_tensor(structure, weights, multiplier)
        return structure

    def run(self, conditioning, early_weights_7, detail_weights_4, refinement_weights_1, multiplier, crossover, overlap):
        group_strings = [early_weights_7, detail_weights_4, refinement_weights_1]
        weights = []
        for (name, layers), group_s in zip(KREA2_GROUPS, group_strings):
            group_weights = self._parse_weights(group_s)
            if len(group_weights) != len(layers):
                raise ValueError(
                    f"[Krea2GatedRebalance] '{name}_weights' needs exactly {len(layers)} value(s) "
                    f"(layers {', '.join(map(str, layers))}) - got {len(group_weights)}"
                )
            weights.extend(group_weights)

        weights = self._blend_weights(weights, crossover, overlap)
        print(f"[Krea2GatedRebalance] effective weights: {[round(w,3) for w in weights]}, multiplier={multiplier}")
        return (self._apply(conditioning, weights, multiplier),)


NODE_CLASS_MAPPINGS = {"Krea2GatedRebalance": Krea2GatedRebalance}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Krea2GatedRebalance": "Krea2 Gated Rebalance"
}
