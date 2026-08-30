from comfy_api.latest import io
from jinja2 import StrictUndefined, Undefined, meta
from jinja2.sandbox import SandboxedEnvironment

DEFAULT_TEMPLATE = "A portrait of {{ subject }}, {{ style }}, lit by {{ light }}."


def template_variables(source):
    """The placeholder names in `source`, in the order they first appear.

    find_undeclared_variables works off the parsed AST, so it sees through
    filters, nesting and (later) {% if %}/{% for %} blocks - a regex over
    {{ ... }} would quietly get those wrong. It returns an unordered set, so
    order is restored from where each name occurs in the text, which is what
    makes the sockets come out top-to-bottom.
    """
    try:
        ast = SandboxedEnvironment().parse(source or "")
    except Exception as e:
        return [], str(e)
    names = meta.find_undeclared_variables(ast)
    return sorted(names, key=lambda name: (source or "").find(name)), None


class JinjaTemplate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JinjaTemplate",
            display_name="Jinja Template",
            category="MiseEnPlace/Formatting",
            description=(
                "Fills placeholders in a template. Write {{ name }} anywhere in the template and "
                "an input socket called 'name' appears on the node; wire anything into it and its "
                "value is substituted. Sockets follow the template as you edit it. Full Jinja is "
                "available if you want it later ({% if %}, {% for %}, filters) - the sockets are "
                "worked out from the parsed template, so those keep working too."
            ),
            inputs=[
                io.String.Input(
                    "template",
                    multiline=True,
                    default=DEFAULT_TEMPLATE,
                    tooltip="Text with {{ placeholders }}. Each distinct placeholder becomes an input socket.",
                ),
                io.Boolean.Input(
                    "strict",
                    optional=True,
                    default=False,
                    tooltip="Off: an unconnected placeholder renders as nothing (and is logged). On: it fails the run instead of quietly producing a half-built prompt.",
                ),
            ],
            outputs=[io.String.Output(display_name="text")],
            # Placeholder sockets are created by the UI and so are not in this
            # schema; this is what lets them reach execute() as kwargs.
            accept_all_inputs=True,
        )

    @classmethod
    def execute(cls, template=DEFAULT_TEMPLATE, strict=False, **context) -> io.NodeOutput:
        source = template or ""
        names, parse_error = template_variables(source)
        if parse_error:
            raise ValueError(f"Jinja Template: could not parse the template - {parse_error}")

        missing = [name for name in names if name not in context]
        if missing and not strict:
            print(f"[JinjaTemplate] no input connected for {missing}; rendering them as empty")

        # Sandboxed, because templates travel inside shared workflow JSON: a
        # plain Environment lets one reach arbitrary Python via
        # {{ ''.__class__.__mro__ }}, and nothing here needs that.
        environment = SandboxedEnvironment(
            undefined=StrictUndefined if strict else Undefined,
            keep_trailing_newline=True,
        )
        try:
            rendered = environment.from_string(source).render(**context)
        except Exception as e:
            raise ValueError(f"Jinja Template: {e}") from e
        return io.NodeOutput(rendered)


def _register_routes():
    """Variable discovery for the UI.

    Parsing happens here rather than in JavaScript so the sockets always match
    what jinja2 will actually look up at render time.
    """
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:  # pragma: no cover - only outside ComfyUI
        print(f"[JinjaTemplate] routes not registered ({e}); the node still renders, "
              "but its placeholder sockets will not update.")
        return

    routes = getattr(getattr(PromptServer, "instance", None), "routes", None)
    if routes is None:
        print("[JinjaTemplate] PromptServer not ready; routes not registered.")
        return

    @routes.post("/miseenplace/jinja/variables")
    async def post_variables(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        names, parse_error = template_variables((body or {}).get("template", ""))
        return web.json_response({"variables": names, "error": parse_error})


_register_routes()


NODE_CLASS_MAPPINGS = {"JinjaTemplate": JinjaTemplate}

NODE_DISPLAY_NAME_MAPPINGS = {"JinjaTemplate": "Jinja Template"}
