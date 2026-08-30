"""
Shared JSON Schema -> response_format helper for the llama-cpp nodes.

Both LlamaCppClient and LlamaCppChatSession accept an optional JSON Schema and
turn it into the same OpenAI-compatible response_format block, so the parsing
and the wire shape live here rather than being duplicated. Prefixed with "_" so
the package's node auto-discovery (see ../../__init__.py) skips it.

llama.cpp's server does the schema -> grammar conversion itself, server-side,
once it sees this in the request - nothing here builds a grammar. That is
deliberate: llama.cpp ships its own JSON-Schema-to-grammar converter, already
tuned against its own grammar engine, and a second, hand-written one living
here could only ever drift from it. The Prompt Builder node's schema
(nodes/prompting/_prompt_schema.py) was written with exactly that converter in
mind - $defs/$ref instead of repetition, oneOf branches discriminated by a
const instead of if/then, no `not` - so wiring its 'schema' output straight
into this socket is the intended path, but nothing here is specific to it: any
JSON Schema text works.
"""

import json
import re

JSON_SCHEMA_TOOLTIP = (
    "Optional. JSON Schema text - e.g. a Prompt Builder node's 'schema' output - that "
    "constrains the reply to match it. The server converts the schema to a grammar itself, so "
    "this works with any schema, not just Prompt Builder's. Invalid JSON is logged and ignored "
    "rather than failing the call; the request just goes out unconstrained."
)


def json_schema_input(**overrides):
    options = {"default": "", "multiline": True, "tooltip": JSON_SCHEMA_TOOLTIP}
    options.update(overrides)
    return ("STRING", options)


def _schema_name(schema):
    """A name for the schema, for the OpenAI-style response_format envelope.

    Servers mostly key off `.schema` alone, but `name` is part of the
    documented contract, so something stable and readable beats a constant:
    the schema's own `title`, sanitised to the identifier shape the spec
    expects (letters, digits, underscore, hyphen), or "response" if it has
    none or the title sanitises down to nothing.
    """
    title = schema.get("title") if isinstance(schema, dict) else None
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_") if isinstance(title, str) else ""
    return (name or "response")[:64]


def response_format(schema):
    """The response_format block for `schema` (already parsed, a dict)."""
    return {
        "type": "json_schema",
        "json_schema": {"name": _schema_name(schema), "strict": True, "schema": schema},
    }


def parse_json_schema(text, log_prefix=""):
    """response_format for `text`, or None if it is blank or not a JSON object.

    A bad schema is reported and treated as "no schema" rather than raised,
    the same way extract_from_reply treats a bad regex (see _llm_text.py): a
    stale or malformed link into this socket should not fail the whole call -
    the request still goes out, just without the constraint.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        schema = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"{log_prefix}json_schema is not valid JSON ({e}); sending the request unconstrained")
        return None
    if not isinstance(schema, dict):
        print(
            f"{log_prefix}json_schema is a {type(schema).__name__}, not an object; "
            "sending the request unconstrained"
        )
        return None
    return response_format(schema)
