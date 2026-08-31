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
                "them. No file on disk, no wire between the two required. If nothing has been "
                "stored yet and no 'default' is given, this raises an error rather than silently "
                "passing None through - important for types like IMAGE, where a bare None crashes "
                "confusingly deep inside a downstream node instead of here."
            ),
            # 'reset' is a side effect performed in execute() (clear()), not
            # something visible in the output value, so a dead-end Buffer
            # Read (nothing downstream consuming 'value') would otherwise be
            # pruned from the run and the reset would silently never happen -
            # see the matching comment on Buffer Write.
            is_output_node=True,
            inputs=[
                io.String.Input(
                    "handle",
                    default="",
                    tooltip="Identifies which buffer to read - match a Buffer Write's 'handle'.",
                ),
                io.AnyType.Input(
                    "default",
                    optional=True,
                    tooltip="Output when nothing has been written yet (or right after 'reset'). Required the first run of a loop - e.g. wire in a blank/placeholder image if 'value' is an IMAGE.",
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
    def fingerprint_inputs(cls, **kwargs):
        # The stored value can change between runs with no other input
        # changing at all - the whole point of the buffer - so this can't be
        # a fingerprint of the current state (ComfyUI only resolves literal/
        # widget inputs here, not wired ones, so a wired `handle` would read
        # back as None and never reflect the real key anyway). Forcing a
        # cache miss on every run is what actually guarantees execute() runs
        # and reads the real, correctly-resolved handle each time.
        return float("nan")

    @classmethod
    def execute(cls, handle="", default=None, reset=False) -> io.NodeOutput:
        if reset:
            clear(handle)
            value, revision = default, 0
        else:
            value, revision = read(handle, default)
        if revision == 0 and default is None:
            # Nothing was ever written for this handle (or it was just reset)
            # and there's no default to fall back to, so this would otherwise
            # hand back a bare None. That's harmless for some types but fatal
            # for IMAGE/LATENT/etc: e.g. Preview Image dies deep inside
            # save_images with a cryptic "'NoneType' object is not
            # subscriptable" instead of pointing at the real cause. Raise here
            # instead, at the source, with an actionable message.
            raise ValueError(
                f"Buffer Read '{handle}' has nothing stored yet and no "
                "'default' was given. Either wire a default value into "
                "'default' (e.g. a blank image), or make sure the paired "
                "Buffer Write for this handle runs at least once first."
            )
        return io.NodeOutput(value)


NODE_CLASS_MAPPINGS = {"BufferRead": BufferRead}

NODE_DISPLAY_NAME_MAPPINGS = {"BufferRead": "Buffer Read"}
