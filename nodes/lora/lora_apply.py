import os
import torch

try:
    from safetensors.torch import load_file as safetensors_load

    HAS_SAFETENSORS = True
except Exception:
    HAS_SAFETENSORS = False


class LoRAApply:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "high_model_in": ("ANY", {"default": None}),
                "low_model_in": ("ANY", {"default": None}),
                "high_lora_path": ("STRING", {"default": ""}),
                "low_lora_path": ("STRING", {"default": ""}),
            },
            "optional": {
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

    def _load_lora_state(self, path, device=None):
        if not path:
            return {}
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext == "safetensors":
            if not HAS_SAFETENSORS:
                raise RuntimeError("safetensors not installed")
            state = safetensors_load(path, device=device or "cpu")
            return {k: v.cpu() for k, v in state.items()}
        else:
            # torch load
            state = torch.load(path, map_location=device or "cpu")
            # if saved as dict with metadata, try common keys
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]
            return {k: v.cpu() for k, v in state.items()}

    def _apply_dict_to_state(
        self, model_state, lora_state, multiplier=1.0, strict_shape=False
    ):
        applied = 0
        mismatches = []
        for lk, lv in lora_state.items():
            if lk in model_state:
                try:
                    if model_state[lk].shape == lv.shape:
                        model_state[lk] = model_state[lk] + lv * multiplier
                        applied += 1
                    else:
                        mismatches.append((lk, model_state[lk].shape, lv.shape))
                except Exception as e:
                    mismatches.append((lk, str(e)))
            else:
                # try suffix match
                candidates = [
                    k
                    for k in model_state.keys()
                    if k.endswith(lk) or lk.endswith(k) or lk in k
                ]
                if candidates:
                    # apply to first candidate with matching shape
                    matched = False
                    for ck in candidates:
                        try:
                            if model_state[ck].shape == lv.shape:
                                model_state[ck] = model_state[ck] + lv * multiplier
                                applied += 1
                                matched = True
                                break
                        except Exception:
                            continue
                    if not matched:
                        mismatches.append((lk, "no matching shape in candidates"))
                else:
                    mismatches.append((lk, "no candidate key"))
        if strict_shape and mismatches:
            raise RuntimeError(f"Shape mismatches applying LoRA: {mismatches}")
        return applied, mismatches

    def _apply_to_module(self, module, lora_state, multiplier=1.0, strict_shape=False):
        # attempt to apply by named_parameters
        name_to_param = {n: p for n, p in module.named_parameters()}
        applied = 0
        mismatches = []
        for lk, lv in lora_state.items():
            if lk in name_to_param:
                p = name_to_param[lk]
                try:
                    if p.data.shape == lv.shape:
                        p.data = p.data + lv.to(p.data.device) * multiplier
                        applied += 1
                    else:
                        mismatches.append((lk, p.data.shape, lv.shape))
                except Exception as e:
                    mismatches.append((lk, str(e)))
            else:
                # try suffix matching
                candidates = [
                    n for n in name_to_param.keys() if n.endswith(lk) or lk in n
                ]
                if candidates:
                    matched = False
                    for ck in candidates:
                        p = name_to_param[ck]
                        try:
                            if p.data.shape == lv.shape:
                                p.data = p.data + lv.to(p.data.device) * multiplier
                                applied += 1
                                matched = True
                                break
                        except Exception:
                            continue
                    if not matched:
                        mismatches.append((lk, "no matching shape in candidates"))
                else:
                    mismatches.append((lk, "no candidate param"))
        if strict_shape and mismatches:
            raise RuntimeError(
                f"Shape mismatches applying LoRA to module: {mismatches}"
            )
        return applied, mismatches

    def run(
        self,
        high_model_in,
        low_model_in,
        high_lora_path,
        low_lora_path,
        multiplier_high=1.0,
        multiplier_low=1.0,
        device="",
        strict_shape=False,
    ):
        status_lines = []
        try:
            device_target = (
                device if device else ("cuda" if torch.cuda.is_available() else "cpu")
            )

            # Load LoRA states
            high_state = {}
            low_state = {}
            if high_lora_path:
                high_state = self._load_lora_state(high_lora_path, device=device_target)
                status_lines.append(
                    f"Loaded high LoRA: {high_lora_path} ({len(high_state)} tensors)"
                )
            if low_lora_path:
                low_state = self._load_lora_state(low_lora_path, device=device_target)
                status_lines.append(
                    f"Loaded low LoRA: {low_lora_path} ({len(low_state)} tensors)"
                )

            # Apply to models
            # High
            if high_model_in is not None and high_state:
                if hasattr(high_model_in, "state_dict"):
                    st = high_model_in.state_dict()
                    # move to CPU tensors
                    st_clean = {k: v.cpu() for k, v in st.items()}
                    applied, mismatches = self._apply_dict_to_state(
                        st_clean, high_state, multiplier_high, strict_shape
                    )
                    status_lines.append(
                        f"Applied high LoRA entries: {applied}, mismatches: {len(mismatches)}"
                    )
                    # load back
                    try:
                        high_model_in.load_state_dict(st_clean, strict=False)
                    except Exception:
                        # try module param assignment
                        for n, p in high_model_in.named_parameters():
                            if n in st_clean:
                                try:
                                    p.data = st_clean[n].to(p.data.device)
                                except Exception:
                                    pass
                else:
                    # try treating as module
                    applied, mismatches = self._apply_to_module(
                        high_model_in, high_state, multiplier_high, strict_shape
                    )
                    status_lines.append(
                        f"Applied high LoRA to module params: {applied}, mismatches: {len(mismatches)}"
                    )

            # Low
            if low_model_in is not None and low_state:
                if hasattr(low_model_in, "state_dict"):
                    st = low_model_in.state_dict()
                    st_clean = {k: v.cpu() for k, v in st.items()}
                    applied, mismatches = self._apply_dict_to_state(
                        st_clean, low_state, multiplier_low, strict_shape
                    )
                    status_lines.append(
                        f"Applied low LoRA entries: {applied}, mismatches: {len(mismatches)}"
                    )
                    try:
                        low_model_in.load_state_dict(st_clean, strict=False)
                    except Exception:
                        for n, p in low_model_in.named_parameters():
                            if n in st_clean:
                                try:
                                    p.data = st_clean[n].to(p.data.device)
                                except Exception:
                                    pass
                else:
                    applied, mismatches = self._apply_to_module(
                        low_model_in, low_state, multiplier_low, strict_shape
                    )
                    status_lines.append(
                        f"Applied low LoRA to module params: {applied}, mismatches: {len(mismatches)}"
                    )

            status = "\n".join(status_lines) or "No LoRAs applied"
            print(status)
            return (high_model_in, low_model_in, status)
        except Exception as e:
            err = f"Error applying LoRA: {e}"
            print(err)
            return (high_model_in, low_model_in, err)


NODE_CLASS_MAPPINGS = {"LoRAApply": LoRAApply}
NODE_DISPLAY_NAME_MAPPINGS = {"LoRAApply": "LoRA Apply (merge into models)"}
