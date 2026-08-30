import time
import uuid


class TimerStart:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "latent_in": ("LATENT", {"default": None}),
                "image_in": ("IMAGE", {"default": None}),
                "string_in": ("STRING", {"default": ""}),
                "int_in": ("INT", {"default": 0}),
                "force_execute": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "STRING", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("latent", "image", "string", "int", "timestamp", "execution_id")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Timing"
    # Disable caching to ensure fresh timestamp on each execution
    CACHE_BYPASSED = True

    def is_changed(self, **kwargs):
        return kwargs.get("force_execute", True)

    def run(self, latent_in=None, image_in=None, string_in="", int_in=0, force_execute=True):
        ts = time.time()
        exec_id = str(uuid.uuid4())
        print(f"Timer started at {ts} (exec_id: {exec_id})")
        return (latent_in, image_in, string_in, int_in, ts, exec_id)


NODE_CLASS_MAPPINGS = {"TimerStart": TimerStart}

NODE_DISPLAY_NAME_MAPPINGS = {"TimerStart": "Timer Start"}
