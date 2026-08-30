import time


class TimerStop:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "start_timestamp": ("FLOAT", {}),
            },
            "optional": {
                "latent_in": ("LATENT", {"default": None}),
                "image_in": ("IMAGE", {"default": None}),
                "string_in": ("STRING", {"default": ""}),
                "int_in": ("INT", {"default": 0}),
                "force_execute": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "STRING", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("latent", "image", "string", "int", "elapsed", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Timing"
    # Disable caching to ensure fresh elapsed time on each execution
    CACHE_BYPASSED = True

    def is_changed(self, **kwargs):
        return kwargs.get("force_execute", True)

    def run(
        self,
        start_timestamp,
        latent_in=None,
        image_in=None,
        string_in="",
        int_in=0,
        force_execute=True,
    ):
        elapsed = time.time() - start_timestamp
        status = f"Elapsed time: {elapsed:.6f}s"
        print(status)
        return (latent_in, image_in, string_in, int_in, elapsed, status)


NODE_CLASS_MAPPINGS = {"TimerStop": TimerStop}

NODE_DISPLAY_NAME_MAPPINGS = {"TimerStop": "Timer Stop"}
