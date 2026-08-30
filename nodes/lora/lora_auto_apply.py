import json
import os

from .lora_loader import LoRALoader
from .lora_apply import LoRAApply


class LoRAAutoApply:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "high_model_in": ("ANY", {"default": None}),
                "low_model_in": ("ANY", {"default": None}),
                "lora_name": ("STRING", {"default": ""}),
            },
            "optional": {
                "search_dirs": ("STRING", {"default": "models/lora,models"}),
                "extensions": ("STRING", {"default": "safetensors,pt"}),
                "auto_high_low": ("BOOLEAN", {"default": True}),
                "recursive": ("BOOLEAN", {"default": True}),
                "multiplier_high": ("FLOAT", {"default": 1.0}),
                "multiplier_low": ("FLOAT", {"default": 1.0}),
                "device": ("STRING", {"default": ""}),
                "strict_shape": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("ANY", "ANY", "STRING")
    RETURN_NAMES = ("high_model", "low_model", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/LoRA"

    def _pick_high_low(self, paths):
        # prefer explicit keywords; return (high_path, low_path)
        def contains_kw(p, kws):
            name = os.path.basename(p).lower()
            return any(kw in name for kw in kws)

        high_kws = ["_high", "-high", "high"]
        low_kws = ["_low", "-low", "low"]

        high_candidates = [p for p in paths if contains_kw(p, high_kws)]
        low_candidates = [p for p in paths if contains_kw(p, low_kws)]

        high = high_candidates[0] if high_candidates else None
        low = low_candidates[0] if low_candidates else None

        # if not found explicitly, fall back to positional
        if not high or not low:
            # try to use two first entries
            if len(paths) >= 2:
                if not high:
                    high = paths[0]
                if not low:
                    low = paths[1]
            elif len(paths) == 1:
                # only one file found; return it as both (user must ensure correctness)
                if not high:
                    high = paths[0]
                if not low:
                    low = paths[0]
        return high, low

    def run(
        self,
        high_model_in,
        low_model_in,
        lora_name,
        search_dirs="models/lora,models",
        extensions="safetensors,pt",
        auto_high_low=True,
        recursive=True,
        multiplier_high=1.0,
        multiplier_low=1.0,
        device="",
        strict_shape=False,
    ):
        status_lines = []
        try:
            loader = LoRALoader()
            # LoRALoader.run returns (found_json, status)
            found_json, loader_status = loader.run(
                lora_name,
                search_dirs=search_dirs,
                extensions=extensions,
                auto_high_low=auto_high_low,
                recursive=recursive,
            )
            status_lines.append(f"Loader: {loader_status}")
            try:
                paths = json.loads(found_json)
            except Exception:
                paths = []

            if not paths:
                msg = f"No LoRA files found for '{lora_name}'"
                status_lines.append(msg)
                print("\n".join(status_lines))
                return (high_model_in, low_model_in, "\n".join(status_lines))

            high_path, low_path = self._pick_high_low(paths)
            status_lines.append(f"Selected high: {high_path}")
            status_lines.append(f"Selected low: {low_path}")

            applier = LoRAApply()
            high_out, low_out, apply_status = applier.run(
                high_model_in,
                low_model_in,
                high_path or "",
                low_path or "",
                multiplier_high=multiplier_high,
                multiplier_low=multiplier_low,
                device=device,
                strict_shape=strict_shape,
            )
            status_lines.append(f"Apply: {apply_status}")

            status = "\n".join(status_lines)
            print(status)
            return (high_out, low_out, status)
        except Exception as e:
            err = f"Error in LoRAAutoApply: {e}"
            print(err)
            return (high_model_in, low_model_in, err)


NODE_CLASS_MAPPINGS = {"LoRAAutoApply": LoRAAutoApply}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LoRAAutoApply": "LoRA Auto Apply (find & merge high/low)"
}
