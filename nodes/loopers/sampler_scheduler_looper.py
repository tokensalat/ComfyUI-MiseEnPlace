class SamplerSchedulerLooper:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "combinations": ("STRING", {"default": "euler,normal|euler,karras"}),
                "index_in": ("INT", {"default": 0}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("sampler", "scheduler", "total", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Loopers"

    def run(self, combinations, index_in):
        # Parse combinations string (format: "a,b|c,d|...")
        combo_list = [
            combo.strip() for combo in combinations.split("|") if combo.strip()
        ]
        total = len(combo_list)

        # Clamp index
        index_in = max(0, min(index_in, total - 1))

        # Get current combo and parse it
        current_combo = combo_list[index_in]
        parts = [p.strip() for p in current_combo.split(",")]
        sampler = parts[0] if len(parts) > 0 else ""
        scheduler = parts[1] if len(parts) > 1 else ""

        # Build status string (1-based index)
        status = f"[{index_in + 1} / {total}] sampler={sampler}, scheduler={scheduler}"
        print(status)

        return (sampler, scheduler, total, status)


NODE_CLASS_MAPPINGS = {"SamplerSchedulerLooper": SamplerSchedulerLooper}

NODE_DISPLAY_NAME_MAPPINGS = {"SamplerSchedulerLooper": "Sampler/Scheduler Looper"}
