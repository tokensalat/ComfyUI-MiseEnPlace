from comfy_api.latest import io

from ._bundle_type import Bundle, parse_keys

MAX_ITEMS = 32


class Bundler(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        template = io.Autogrow.TemplatePrefix(
            input=io.AnyType.Input("item"),
            prefix="item",
            min=1,
            max=MAX_ITEMS,
        )
        return io.Schema(
            node_id="Bundler",
            display_name="Bundler",
            category="MiseEnPlace/Bundling",
            description=(
                "Collects any number of connections of any type into a single BUNDLE output. "
                "Connect items in order; a new slot appears automatically. Each slot takes the "
                "name and type of whatever you connect to it, filling the comma-separated 'keys' "
                "list (in connection order) - edit it to rename, or leave a slot blank to fall "
                "back to item0, item1, ..."
            ),
            inputs=[
                io.String.Input(
                    "keys",
                    optional=True,
                    default="",
                    tooltip="Optional comma-separated names for the connected items, in connection order.",
                ),
                io.Autogrow.Input("items", template=template),
            ],
            outputs=[
                Bundle.Output(display_name="bundle"),
            ],
        )

    @classmethod
    def execute(cls, items: io.Autogrow.Type, keys: str = "") -> io.NodeOutput:
        names = parse_keys(keys)
        bundle = {}
        for i, value in enumerate(items.values()):
            key = names[i] if i < len(names) and names[i] else f"item{i}"
            bundle[key] = value
        return io.NodeOutput(bundle)


NODE_CLASS_MAPPINGS = {"Bundler": Bundler}

NODE_DISPLAY_NAME_MAPPINGS = {"Bundler": "Bundler"}
