from comfy_api.latest import io

from ._buffer_state import write


class BufferWrite(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="BufferWrite",
            display_name="Buffer Write",
            category="MiseEnPlace/Feedback",
            description=(
                "Half of a feedback-loop pair with Buffer Read. Stores 'value' - any type - under "
                "the buffer identified by 'handle', a plain string - type the same one into both "
                "nodes to pair them - for that same Buffer Read to hand back on the next queue "
                "run. Passes 'value' through unchanged so this node can sit inline rather than at "
                "a dead end."
            ),
            inputs=[
                io.String.Input(
                    "handle",
                    default="",
                    tooltip="Identifies which buffer to store into - match a Buffer Read's 'handle'.",
                ),
                io.AnyType.Input(
                    "value",
                    tooltip="Stored for the paired Buffer Read to output on the next run.",
                ),
            ],
            outputs=[
                io.AnyType.Output(display_name="value"),
            ],
        )

    @classmethod
    def execute(cls, handle, value) -> io.NodeOutput:
        revision = write(handle, value)
        print(f"[BufferWrite:{handle}] stored revision {revision}")
        return io.NodeOutput(value)


NODE_CLASS_MAPPINGS = {"BufferWrite": BufferWrite}

NODE_DISPLAY_NAME_MAPPINGS = {"BufferWrite": "Buffer Write"}
