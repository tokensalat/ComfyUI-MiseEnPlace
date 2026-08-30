from comfy.samplers import SAMPLER_NAMES, SCHEDULER_NAMES


class SamplerSchedulerSelector:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "sampler": (SAMPLER_NAMES,),
                "scheduler": (SCHEDULER_NAMES,),
            }
        }

    RETURN_TYPES = (SAMPLER_NAMES, SCHEDULER_NAMES, "STRING", "STRING")
    RETURN_NAMES = (
        "sampler_combo",
        "scheduler_combo",
        "sampler_text",
        "scheduler_text",
    )
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Selectors"

    def run(self, sampler, scheduler):
        return (sampler, scheduler, sampler, scheduler)


NODE_CLASS_MAPPINGS = {"SamplerSchedulerSelector": SamplerSchedulerSelector}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SamplerSchedulerSelector": "Sampler & Scheduler Selector"
}
