from comfy.samplers import SAMPLER_NAMES, SCHEDULER_NAMES


class StringFormatter:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prefix": ("STRING", {"default": ""}),
                "video_model": ("STRING", {"default": ""}),
                "sampler": (SAMPLER_NAMES,),
                "scheduler": (SCHEDULER_NAMES,),
                "index": ("INT", {"default": 0, "min": 0, "max": 10000}),
                "runtime": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.01}),
                "string_format": (
                    "STRING",
                    {
                        "default": "{prefix}-{video_model}-{sampler}-{scheduler}-{index}-{runtime:.0f}s",
                        "multiline": True,
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("formatted_string",)
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Formatting"

    def run(
        self, prefix, video_model, sampler, scheduler, index, runtime, string_format
    ):
        try:
            # Render the f-string template with provided inputs
            formatted = string_format.format(
                prefix=prefix,
                video_model=video_model,
                sampler=sampler,
                scheduler=scheduler,
                index=index,
                runtime=runtime,
            )
            print(f"Formatted string: {formatted}")
            return (formatted,)
        except Exception as e:
            error_msg = f"Error formatting string: {str(e)}"
            print(error_msg)
            return (error_msg,)


NODE_CLASS_MAPPINGS = {"StringFormatter": StringFormatter}

NODE_DISPLAY_NAME_MAPPINGS = {"StringFormatter": "String Formatter"}
