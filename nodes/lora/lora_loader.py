import os
import glob
import json


class LoRALoader:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "models": ("STRING", {"default": ""}),
            },
            "optional": {
                "search_dirs": ("STRING", {"default": "models/lora,models"}),
                "extensions": ("STRING", {"default": "safetensors,pt"}),
                "auto_high_low": ("BOOLEAN", {"default": True}),
                "recursive": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("found_paths_json", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/LoRA"

    def _find_files_in_dirs(self, pattern, search_dirs, recursive):
        results = []
        for d in search_dirs:
            d = d.strip()
            if not d:
                continue
            if not os.path.isabs(d):
                # allow relative paths
                base = os.path.join(os.getcwd(), d)
            else:
                base = d

            if not os.path.exists(base):
                continue

            if recursive:
                for root, _, _ in os.walk(base):
                    matches = glob.glob(os.path.join(root, pattern))
                    results.extend(matches)
            else:
                matches = glob.glob(os.path.join(base, pattern))
                results.extend(matches)
        # de-duplicate while preserving order
        seen = set()
        out = []
        for p in results:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _try_find_variant(self, name, exts, search_dirs, recursive, variant_keywords):
        # variant_keywords is list like ["high","lora_high"] etc.
        found = []
        # if the name already points to a file, accept it
        if os.path.exists(name) and os.path.isfile(name):
            return [os.path.abspath(name)]

        # strip extension from name if provided
        base_name = os.path.splitext(name)[0]

        # check direct matches with extensions
        for ext in exts:
            cand = f"{base_name}.{ext}"
            matches = self._find_files_in_dirs(cand, search_dirs, recursive)
            if matches:
                found.extend(matches)
                return found

        # search variants containing keyword
        for kw in variant_keywords:
            for ext in exts:
                pattern = f"*{base_name}*{kw}*.{ext}"
                matches = self._find_files_in_dirs(pattern, search_dirs, recursive)
                if matches:
                    found.extend(matches)
                    # we don't return immediately; collect all variants for a name
        # fallback: any file containing base_name
        if not found:
            for ext in exts:
                pattern = f"*{base_name}*.{ext}"
                matches = self._find_files_in_dirs(pattern, search_dirs, recursive)
                if matches:
                    found.extend(matches)
        return found

    def run(
        self,
        models,
        search_dirs="models/lora,models",
        extensions="safetensors,pt",
        auto_high_low=True,
        recursive=True,
    ):
        try:
            exts = [e.strip().lstrip(".") for e in extensions.split(",") if e.strip()]
            dirs = [d.strip() for d in search_dirs.split(",") if d.strip()]
            names = [
                m.strip() for m in models.replace("\n", ",").split(",") if m.strip()
            ]

            results = []
            status_lines = []

            for name in names:
                # for each requested model name try to find high/low variants
                if auto_high_low:
                    # prefer explicit high/low keywords
                    high_matches = self._try_find_variant(
                        name, exts, dirs, recursive, ["_high", "-high", "high"]
                    )
                    low_matches = self._try_find_variant(
                        name, exts, dirs, recursive, ["_low", "-low", "low"]
                    )
                    # if we found both, add high then low
                    if high_matches:
                        results.extend(high_matches)
                        status_lines.append(
                            f"Found high variant(s) for {name}: {high_matches}"
                        )
                    if low_matches:
                        results.extend(low_matches)
                        status_lines.append(
                            f"Found low variant(s) for {name}: {low_matches}"
                        )

                    # if neither specifically found, try any matches
                    if not high_matches and not low_matches:
                        any_matches = self._try_find_variant(
                            name, exts, dirs, recursive, []
                        )
                        if any_matches:
                            results.extend(any_matches)
                            status_lines.append(
                                f"Found variant(s) for {name}: {any_matches}"
                            )
                        else:
                            status_lines.append(f"No matches for {name}")
                else:
                    matches = self._try_find_variant(name, exts, dirs, recursive, [])
                    if matches:
                        results.extend(matches)
                        status_lines.append(f"Found: {matches}")
                    else:
                        status_lines.append(f"No matches for {name}")

            # dedupe preserving order
            seen = set()
            final_paths = []
            for p in results:
                ap = os.path.abspath(p)
                if ap not in seen:
                    seen.add(ap)
                    final_paths.append(ap)

            found_json = json.dumps(final_paths)
            status = "\n".join(status_lines) or "No models requested"
            print(status)
            return (found_json, status)
        except Exception as e:
            err = f"Error searching LoRAs: {e}"
            print(err)
            return ("[]", err)


NODE_CLASS_MAPPINGS = {"LoRALoader": LoRALoader}

NODE_DISPLAY_NAME_MAPPINGS = {"LoRALoader": "LoRA Loader (auto high/low, multi)"}
