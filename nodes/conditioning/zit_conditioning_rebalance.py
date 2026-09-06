import torch

# Z-Image Turbo conditions on a single Qwen3-4B hidden state (one tensor), not
# a stack of concatenated encoder taps the way Krea2 does - so Krea2GatedRebalance's
# per-tap axis has nothing to act on here. Ported from DonutsDelivery/ComfyUI-DonutNodes'
# DonutZitConditioningRebalance.py, minus its "multiplier" - Z-Image's NextDiT.cap_embedder
# (comfy/ldm/lumina/model.py) starts with RMSNorm(cap_feats) before anything else, and
# RMSNorm(c*x) == RMSNorm(x) for any positive c: a flat gain on the whole embedding is
# provably cancelled the instant it reaches the model, unlike Krea2's txtfusion (which
# combines taps through residual blocks - x = x + attn(prenorm(x)) - so a flat gain there
# actually survives). Only per_channel_weights carries over: RMSNorm collapses everything
# to one scalar magnitude per token, but doesn't erase the *relative* weighting between
# channels introduced beforehand, so uneven bands still have a real effect.


class ZitConditioningRebalance:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "per_channel_weights": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Comma/semicolon list of gains spread as contiguous bands across the embedding's feature channels (e.g. 2560 dims). Empty = uniform (no-op).",
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

    def _scale_tensor(self, t, weights):
        if not weights:
            return t
        # band i covers a contiguous range of channels; works for any k <= d
        d = t.shape[-1]
        k = len(weights)
        orig_dtype = t.dtype
        idx = (torch.arange(d, device=t.device) * k // d).clamp(max=k - 1)
        gains = torch.tensor(weights, dtype=torch.float32, device=t.device)[idx]
        return (t.float() * gains).to(orig_dtype)

    def _apply(self, structure, weights):
        if isinstance(structure, list):
            out = []
            for item in structure:
                if (isinstance(item, (list, tuple)) and len(item) == 2
                        and isinstance(item[0], torch.Tensor)
                        and isinstance(item[1], dict)):
                    cond_t, extras = item
                    out.append([self._scale_tensor(cond_t, weights), dict(extras)])
                else:
                    out.append(self._apply(item, weights))
            return out
        if isinstance(structure, torch.Tensor):
            return self._scale_tensor(structure, weights)
        return structure

    def run(self, conditioning, per_channel_weights=""):
        weights = self._parse_weights(per_channel_weights)
        print(f"[ZitConditioningRebalance] {len(weights)} channel band(s)" if weights else "[ZitConditioningRebalance] uniform (no per-channel weights) - no-op")
        return (self._apply(conditioning, weights),)


NODE_CLASS_MAPPINGS = {"ZitConditioningRebalance": ZitConditioningRebalance}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZitConditioningRebalance": "ZiT Conditioning Rebalance"
}
