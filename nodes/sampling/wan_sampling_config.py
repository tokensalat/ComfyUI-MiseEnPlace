class WanSamplingConfig:
    """Single source of truth for a WAN 2.2 dual-model (high-noise / low-noise) sampling pass.
    Grabs width/height off the source image so downstream latent/size nodes don't need their
    own copy, and turns total_steps + split_ratio into a boundary_step: wire that as
    end_at_step on the high-noise KSamplerAdvanced and as start_at_step on the low-noise one."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "total_steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
                "split_ratio": (
                    "FLOAT",
                    {
                        "default": 0.2,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.01,
                        "tooltip": "Fraction of total_steps spent on the high-noise expert before handing off to the low-noise expert.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT")
    RETURN_NAMES = ("width", "height", "total_steps", "boundary_step")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Sampling"

    def run(self, image, total_steps, split_ratio):
        _batch, height, width, _channels = image.shape
        boundary_step = min(total_steps, max(0, round(total_steps * split_ratio)))
        return (width, height, total_steps, boundary_step)


NODE_CLASS_MAPPINGS = {"WanSamplingConfig": WanSamplingConfig}

NODE_DISPLAY_NAME_MAPPINGS = {"WanSamplingConfig": "WAN Sampling Config"}
