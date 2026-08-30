"""
Shared LLM_CONFIG type for the llama-cpp nodes.

One LlamaCppConfig node carries the connection and sampling settings that
LlamaCppClient and LlamaCppChatSession would otherwise each duplicate, and
hands them over a single typed socket. Prefixed with "_" so the package's node
auto-discovery (see ../../__init__.py) skips importing it as a node module.

Prompts are deliberately NOT part of this: system_prompt and the per-call
prompt/message stay on the calling node, where they belong. The config is
connection and sampling only, so one config can be shared by nodes that each
speak with their own voice.

Resolution rule, deliberately one line long so it stays predictable: a field
the config carries wins over the calling node's own widget. Nothing is merged
per-value and nothing is inferred from whether a widget still holds its
default - see merge_settings().
"""

LLM_CONFIG = "LLM_CONFIG"

# Single source of truth for the shared widgets. The client nodes pull their
# specs from here via field() so defaults and ranges can only be changed in one
# place, while still declaring them in their own order (widget order is what
# saved widgets_values are keyed on positionally, so it must not shift).
SHARED_FIELDS = {
    "url": ("STRING", {"default": "http://localhost:8080/v1/chat/completions"}),
    "timeout": ("INT", {"default": 300, "min": 1, "max": 3600}),
    "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.01}),
    "repeat_penalty": ("FLOAT", {"default": 1.1, "min": 0.0, "max": 2.0, "step": 0.01}),
    "top_k": ("INT", {"default": 40, "min": 0, "max": 100}),
    "top_p": ("FLOAT", {"default": 0.95, "min": 0.0, "max": 1.0, "step": 0.01}),
    "min_p": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01}),
    "presence_penalty": ("FLOAT", {"default": 0.0, "min": -2.0, "max": 2.0, "step": 0.01}),
    "min_image_tokens": ("INT", {"default": 64, "min": 1, "max": 1024}),
    "max_image_tokens": ("INT", {"default": 256, "min": 1, "max": 2048}),
    "do_image_splitting": ("BOOLEAN", {"default": True}),
    "seed": ("INT", {"default": -1, "min": -1, "max": 0x7FFFFFFF}),
}

CONFIG_INPUT = (
    LLM_CONFIG,
    {"tooltip": "Optional. Connect a Llama-cpp Config node to drive the settings it covers; those widgets are then ignored (the UI greys them out). Leave it unconnected and this node's own widgets apply, exactly as before."},
)


def field(name, **overrides):
    """The shared spec for `name`, with per-node tweaks applied."""
    io_type, options = SHARED_FIELDS[name]
    options = dict(options)
    options.update(overrides)
    return (io_type, options)


def merge_settings(config, local):
    """Resolved settings: whatever the config carries beats the local widget."""
    merged = dict(local)
    if isinstance(config, dict):
        for name in SHARED_FIELDS:
            if name in config:
                merged[name] = config[name]
    return merged
