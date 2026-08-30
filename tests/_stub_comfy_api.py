"""Installs a minimal stand-in for comfy_api.latest.io into sys.modules.

V3-schema nodes (prompt_builder.py among them) do `from comfy_api.latest
import io` at module scope and subclass `io.ComfyNode`. The real module pulls
in torch and the rest of the ComfyUI runtime, which these tests don't need and
shouldn't require just to exercise plain-Python logic. This stub provides just
enough - ComfyNode, Schema, NodeOutput, Hidden, and widget-type placeholders -
for those modules to import and their execute() classmethods to run. It is not
a faithful reimplementation of the real API; anything beyond "does this class
of node import and run" belongs in a real ComfyUI environment, not here.

Call install() before importing anything under nodes/ that touches comfy_api.
"""

import sys
import types


def install():
    if "comfy_api.latest.io" in sys.modules:
        return sys.modules["comfy_api.latest.io"]

    comfy_api = types.ModuleType("comfy_api")
    latest = types.ModuleType("comfy_api.latest")
    io = types.ModuleType("comfy_api.latest.io")

    class ComfyNode:
        pass

    class Schema:
        def __init__(self, **kwargs):
            pass

    class NodeOutput:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class Hidden:
        unique_id = "UNIQUE_ID"

    io.ComfyNode = ComfyNode
    io.Schema = Schema
    io.NodeOutput = NodeOutput
    io.Hidden = Hidden
    for name in ("String", "Int", "Boolean", "AnyType"):
        placeholder = type(
            name,
            (),
            {
                "Input": staticmethod(lambda *a, **kw: None),
                "Output": staticmethod(lambda *a, **kw: None),
            },
        )
        setattr(io, name, placeholder)

    comfy_api.latest = latest
    latest.io = io
    sys.modules["comfy_api"] = comfy_api
    sys.modules["comfy_api.latest"] = latest
    sys.modules["comfy_api.latest.io"] = io
    return io
