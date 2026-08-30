from ._llm_config import LLM_CONFIG, SHARED_FIELDS, field


class LlamaCppConfig:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {name: field(name) for name in SHARED_FIELDS}}

    RETURN_TYPES = (LLM_CONFIG,)
    RETURN_NAMES = ("config",)
    FUNCTION = "build"
    CATEGORY = "MiseEnPlace/LLM"
    DESCRIPTION = (
        "Connection and sampling settings for the llama-cpp nodes, in one place. Wire 'config' "
        "into Llama-cpp Client and Llama-cpp Chat Session and they use these instead of their "
        "own copies of the same widgets. Prompts are not included - the system prompt and the "
        "per-call prompt/message stay on the calling node, so one config can serve several nodes "
        "that each speak differently."
    )

    def build(self, **settings):
        # Every field is required, so this is just the widget values as-is.
        # merge_settings() on the consuming side keys off which names are
        # present, so don't add anything here that isn't a real setting.
        return ({name: settings[name] for name in SHARED_FIELDS},)


NODE_CLASS_MAPPINGS = {"LlamaCppConfig": LlamaCppConfig}

NODE_DISPLAY_NAME_MAPPINGS = {"LlamaCppConfig": "Llama-cpp Config"}
