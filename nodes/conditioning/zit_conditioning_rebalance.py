import torch

# Z-Image Turbo conditions on a single Qwen3-4B hidden state (one tensor), not
# a stack of concatenated encoder taps the way Krea2 does - so Krea2GatedRebalance's
# per-tap axis has nothing to act on here. Ported from DonutsDelivery/ComfyUI-DonutNodes'
# DonutZitConditioningRebalance.py, minus its "multiplier" - Z-Image's NextDiT.cap_embedder
# (comfy/ldm/lumina/model.py) starts with RMSNorm(cap_feats) before anything else, and
# RMSNorm(c*x) == RMSNorm(x) for any positive c: a flat gain on the whole embedding, or on
# every channel band by the same factor, is provably cancelled the instant it reaches the
# model (scaling a vector uniformly - even a vector with non-uniform per-channel content -
# is still a uniform rescale of it). Unlike Krea2's txtfusion, which combines taps through
# residual blocks (x = x + attn(prenorm(x))) and so preserves a flat gain's effect, Z-Image's
# path is a hard normalize-and-replace with no residual to carry a magnitude change through.
#
# Two modes that DO survive, because neither is a uniform rescale of the whole tensor:
# "multiply" - per_channel_weights as per-channel gain (1.0 = no change). RMSNorm collapses
#   everything to one scalar magnitude per token, but doesn't erase the *relative* weighting
#   between channels.
# "add" - per_channel_weights as a per-channel additive bias (0.0 = no change). RMSNorm(x+b)
#   != RMSNorm(x) in general, unlike RMSNorm(c*x): a shift changes both the direction and the
#   magnitude RMSNorm measures. Structurally sound, but shifting a semantic embedding by a
#   constant has no established precedent the way scaling it does - unverified how it reads
#   perceptually, so treat it as the experimental option.
# crossover/overlap (same blend as Krea2GatedRebalance/ZitBlockGatedRebalance) blends each
# band's value toward the mode's own identity (1.0 for multiply, 0.0 for add) by position,
# which survives for the same reason per_channel_weights does: it changes the vector's shape,
# not just a uniform magnitude.


class ZitConditioningRebalance:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "mode": (
                    ["multiply", "add"],
                    {"default": "multiply", "tooltip": "multiply: per_channel_weights are gains (1.0 = no change). add: per_channel_weights are biases (0.0 = no change) - survives RMSNorm the same way, but its effect on quality is unverified."},
                ),
                "per_channel_weights": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Comma/semicolon list of values spread as contiguous bands across the embedding's feature channels (e.g. 2560 dims) - gains in 'multiply' mode, biases in 'add' mode. Empty = no-op.",
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

    def _blend_weights(self, weights, crossover, overlap, identity):
        """Same crossover/overlap smooth-step gating as Krea2GatedRebalance, applied by band
        position - blending each value toward `identity` (the mode's own no-op value) instead
        of always 1.0, so it works the same way for both 'multiply' (identity=1.0) and 'add'
        (identity=0.0)."""
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

            blended.append(identity + blend * (w - identity))

        return blended

    def _scale_tensor(self, t, weights, mode):
        if not weights:
            return t
        # band i covers a contiguous range of channels; works for any k <= d
        d = t.shape[-1]
        k = len(weights)
        orig_dtype = t.dtype
        idx = (torch.arange(d, device=t.device) * k // d).clamp(max=k - 1)
        gains = torch.tensor(weights, dtype=torch.float32, device=t.device)[idx]
        t = t.float()
        t = t * gains if mode == "multiply" else t + gains
        return t.to(orig_dtype)

    def _apply(self, structure, weights, mode):
        if isinstance(structure, list):
            out = []
            for item in structure:
                if (isinstance(item, (list, tuple)) and len(item) == 2
                        and isinstance(item[0], torch.Tensor)
                        and isinstance(item[1], dict)):
                    cond_t, extras = item
                    out.append([self._scale_tensor(cond_t, weights, mode), dict(extras)])
                else:
                    out.append(self._apply(item, weights, mode))
            return out
        if isinstance(structure, torch.Tensor):
            return self._scale_tensor(structure, weights, mode)
        return structure

    def run(self, conditioning, mode="multiply", per_channel_weights="", crossover=0.0, overlap=0.0):
        weights = self._parse_weights(per_channel_weights)
        identity = 1.0 if mode == "multiply" else 0.0
        weights = self._blend_weights(weights, crossover, overlap, identity)
        print(f"[ZitConditioningRebalance] mode={mode}, effective per-channel values: {[round(w, 3) for w in weights]}" if weights else f"[ZitConditioningRebalance] mode={mode}, no per_channel_weights - no-op")
        return (self._apply(conditioning, weights, mode),)


NODE_CLASS_MAPPINGS = {"ZitConditioningRebalance": ZitConditioningRebalance}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZitConditioningRebalance": "ZiT Conditioning Rebalance"
}
