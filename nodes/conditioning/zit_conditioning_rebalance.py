import torch

# Z-Image Turbo conditions on a single Qwen3-4B hidden state (one tensor), not
# a stack of concatenated encoder taps the way Krea2 does - so Krea2GatedRebalance's
# per-tap axis has nothing to act on here. Ported from DonutsDelivery/ComfyUI-DonutNodes'
# DonutZitConditioningRebalance.py: a global gain on the embedding, plus optional
# gains spread as contiguous bands across its feature channels (e.g. 2560 dims) -
# the closest analog to per-layer weighting available on a single-layer conditioning.
# This scales the cross-attention K/V source (Comfy's convert_cond takes index 0 of
# each conditioning pair as `cross_attn` verbatim), which is why it matters most for
# distilled turbo models pinned at CFG 1, where CFG offers no strength control.


class ZitConditioningRebalance:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "multiplier": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": -1e9,
                        "max": 1e9,
                        "step": 0.01,
                        "tooltip": "Global gain on the embedding fed to cross-attention. >1 strengthens prompt adherence; 1.0 = no change.",
                    },
                ),
                "per_channel_weights": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional comma/semicolon list of gains spread as contiguous bands across the embedding's feature channels (e.g. 2560 dims). Empty = uniform. Multiplies on top of multiplier.",
                    },
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

    def _scale_tensor(self, t, weights, multiplier):
        t = t * multiplier
        if not weights:
            return t
        # band i covers a contiguous range of channels; works for any k <= d
        d = t.shape[-1]
        k = len(weights)
        orig_dtype = t.dtype
        idx = (torch.arange(d, device=t.device) * k // d).clamp(max=k - 1)
        gains = torch.tensor(weights, dtype=torch.float32, device=t.device)[idx]
        return (t.float() * gains).to(orig_dtype)

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

    def run(self, conditioning, multiplier, per_channel_weights=""):
        weights = self._parse_weights(per_channel_weights)
        print(f"[ZitConditioningRebalance] multiplier={multiplier}, {len(weights)} channel band(s)" if weights else f"[ZitConditioningRebalance] multiplier={multiplier}, uniform (no per-channel weights)")
        return (self._apply(conditioning, weights, multiplier),)


NODE_CLASS_MAPPINGS = {"ZitConditioningRebalance": ZitConditioningRebalance}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZitConditioningRebalance": "ZiT Conditioning Rebalance"
}
