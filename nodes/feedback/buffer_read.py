import json

from comfy_api.latest import io

from ._buffer_state import clear, read


class BufferRead(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="BufferRead",
            display_name="Buffer Read",
            category="MiseEnPlace/Feedback",
            description=(
                "Half of a feedback-loop pair with Buffer Write. Outputs whatever a Buffer Write "
                "stored under the same 'handle' on the previous queue run (or 'default' the first "
                "time). 'handle' is a plain string - type the same one into both nodes to pair "
                "them. No file on disk, no wire between the two required."
            ),
            inputs=[
                io.String.Input(
                    "handle",
                    default="",
                    tooltip="Identifies which buffer to read - match a Buffer Write's 'handle'.",
                ),
                io.AnyType.Input(
                    "default",
                    optional=True,
                    tooltip="Output when nothing has been written yet (or right after 'reset').",
                ),
                io.Boolean.Input(
                    "reset",
                    optional=True,
                    default=False,
                    tooltip="Discard the stored value and output 'default' instead, for this run and until a Buffer Write stores something new.",
                ),
            ],
            outputs=[
                io.AnyType.Output(display_name="value"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, handle="", default=None, reset=False, **kwargs):
        # The stored value can change between runs with no other input
        # changing at all - the whole point of the buffer - so the revision
        # has to be part of the fingerprint or a cached run would keep
        # answering with a stale value forever.
        _, revision = read(handle, default)
        return json.dumps([revision, reset, repr(default)])

    @classmethod
    def execute(cls, handle="", default=None, reset=False) -> io.NodeOutput:
        if reset:
            clear(handle)
            value = default
        else:
            value, _ = read(handle, default)
        return io.NodeOutput(value)


NODE_CLASS_MAPPINGS = {"BufferRead": BufferRead}

NODE_DISPLAY_NAME_MAPPINGS = {"BufferRead": "Buffer Read"}
