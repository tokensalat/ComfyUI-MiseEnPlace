from comfy_api.latest import io

from ._bundle_type import Bundle, parse_keys

MAX_OVERRIDES = 32


class Piercer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        template = io.Autogrow.TemplatePrefix(
            input=io.AnyType.Input("override"),
            prefix="override",
            min=0,
            max=MAX_OVERRIDES,
        )
        return io.Schema(
            node_id="Piercer",
            display_name="Piercer",
            category="MiseEnPlace/Bundling",
            description=(
                "Overrides values inside a BUNDLE by name. Connect override values in order; each "
                "slot takes the name and type of what you connect, filling the comma-separated "
                "'keys' list (in connection order) - edit it to target a differently named bundle "
                "key. Keys not already in the bundle are added. Outputs the modified BUNDLE."
            ),
            inputs=[
                Bundle.Input("bundle"),
                io.String.Input(
                    "keys",
                    default="",
                    tooltip="Comma-separated bundle keys, in connection order, matching the override inputs below.",
                ),
                io.Autogrow.Input("overrides", template=template),
            ],
            outputs=[
                Bundle.Output(display_name="bundle"),
            ],
        )

    @classmethod
    def execute(cls, bundle, overrides: io.Autogrow.Type = None, keys: str = "") -> io.NodeOutput:
        names = parse_keys(keys)
        result = dict(bundle or {})
        for i, value in enumerate((overrides or {}).values()):
            if i >= len(names) or not names[i]:
                continue
            result[names[i]] = value
        return io.NodeOutput(result)


NODE_CLASS_MAPPINGS = {"Piercer": Piercer}

NODE_DISPLAY_NAME_MAPPINGS = {"Piercer": "Piercer"}
