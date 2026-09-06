from comfy_api.latest import io

from ._bundle_type import Bundle, parse_keys

# ComfyUI's V3 schema has no dynamic-output equivalent of Autogrow (dynamic
# growth only works for inputs), so Unbundler declares a bank of ANY outputs
# and maps requested keys onto them positionally instead. This is the ceiling,
# not what you see: web/js/bundling_sync.js adds and removes output sockets on
# the node to match the bundle actually wired in, the way Pipe Unpacker does.
# A prompt only records links by slot index, so the canvas showing fewer
# sockets than are declared here is fine. Matches MAX_ITEMS in bundler.py.
MAX_OUTPUTS = 32


class Unbundler(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="Unbundler",
            display_name="Unbundler",
            category="MiseEnPlace/Bundling",
            description=(
                "Extracts values back out of a BUNDLE by name. Connect a bundle and the output "
                "sockets take the keys' names and types; 'keys' lists them comma-separated, and "
                "each maps to the output socket in the same position. Edit it to reorder or pick "
                f"a subset. Missing/unused keys output None. Up to {MAX_OUTPUTS} keys."
            ),
            inputs=[
                Bundle.Input("bundle"),
                io.String.Input(
                    "keys",
                    default="",
                    tooltip=f"Comma-separated bundle keys to extract, in order (max {MAX_OUTPUTS}).",
                ),
            ],
            outputs=[
                io.AnyType.Output(display_name=f"value_{i + 1}") for i in range(MAX_OUTPUTS)
            ],
        )

    @classmethod
    def execute(cls, bundle, keys: str = "") -> io.NodeOutput:
        bundle = bundle or {}
        names = parse_keys(keys)
        # Unconditional, so a re-execution with an unchanged graph is visible in the
        # server console - if this line doesn't reappear on a requeue, this node was
        # served from cache and whatever re-ran is downstream, not here.
        print(f"[Unbundler] keys={keys!r}, bundle keys={list(bundle.keys())}")
        if len(names) > MAX_OUTPUTS:
            print(f"Unbundler: {len(names)} keys requested but only {MAX_OUTPUTS} outputs available; extra keys ignored.")
            names = names[:MAX_OUTPUTS]

        if bundle:
            if not names:
                print(f"Unbundler: 'keys' is empty but the incoming bundle has keys {list(bundle.keys())}; every output will be None. "
                      "If 'keys' is exposed through a subgraph boundary, check it didn't default to an unconnected/empty value.")
            else:
                missing = [name for name in names if name and name not in bundle]
                if missing:
                    print(f"Unbundler: key(s) {missing} not found in bundle; available keys: {list(bundle.keys())}. Outputting None for them.")

        values = [bundle.get(name) if name else None for name in names]
        values += [None] * (MAX_OUTPUTS - len(values))
        return io.NodeOutput(*values)


NODE_CLASS_MAPPINGS = {"Unbundler": Unbundler}

NODE_DISPLAY_NAME_MAPPINGS = {"Unbundler": "Unbundler"}
