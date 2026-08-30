"""The JSON contract the prompt builder speaks, and the code that honours it.

Schema, parser and renderer live together on purpose: the schema is what an LLM
gets constrained with, the parser reads what comes back, and the renderer turns
it into the prompt. Split across files they drift; here a change to one is in
sight of the other two.

The document is a bare JSON array of operations, applied to the standing prompt
in order::

    [
      {"section": "style", "op": "add", "position": 0, "content": "35mm film"},
      {"section": "mood", "op": "modify", "content": "still, held breath"},
      {"section": "lighting", "op": "delete"}
    ]

There is no wrapper object and no separate "replace everything" mode - every
document edits whatever prompt is already standing. To start over, pair a
document that adds every section you want with the node's own `reset` input,
which empties the standing prompt before the document is applied. That keeps
"clear the slate" a decision the caller makes on purpose, not something a
document can trigger by omission, or by a flag nobody reads reliably - the
previous shape had exactly that flag, and reading it wrong was its own class of
bug. This shape has nothing to misread: every operation says outright what it
does.

Three operations, and each names exactly the fields it needs:

add
    Inserts a new section. `content` is its text; `position` says where - see
    `_resolve_position` for exactly how a position is read. The section must
    not already exist.
modify
    Changes an existing section's `content` in place. Never repositions it -
    only `add` can say where something goes, so a section stays where it was
    put until something explicitly builds the prompt differently around it.
delete
    Removes an existing section. Takes nothing but the name.

`content` is always a non-empty string. There is no falsy value that means
"delete" - a section comes out only when a document asks for it by name with
`op: delete`, because a value that arrives null or empty is a generation that
went wrong far more often than a deletion anybody meant.
"""

import json

OPS = ("add", "modify", "delete")

_OP_DESCRIPTIONS = {
    "add": "Insert a new section. The section must not already exist.",
    "modify": "Change an existing section's content, leaving its position alone.",
    "delete": "Remove an existing section.",
}

_POSITION_DESCRIPTION = (
    "Where to insert the new section. 0 is the very beginning; the number of "
    "sections currently in the prompt (or -1) appends it at the end; anything "
    "between inserts before the section currently at that index. A position "
    "outside that range is clamped to whichever end it overshot."
)
_CONTENT_DESCRIPTION = "The section's content. Never null or empty."


def build_schema(section_names=None):
    """A JSON Schema for the document, optionally pinned to known section names.

    Handed out as an output so it can go straight into a structured-output or
    grammar-constrained request: whatever the model then produces is something
    parse_document can read.

    The three operations are separate branches of a oneOf, each discriminated
    by a const `op` and listing only the fields that operation accepts, under
    additionalProperties false - rather than one branch with if/then rules
    about which fields go together. Both say the same thing to a validator,
    but only the branch-per-shape form survives the trip through a
    JSON-Schema-to-grammar converter: those resolve a fixed keyword set that
    does not reliably include `if`/`then`, so a rule expressed that way can
    validate correctly while a grammar built from the same schema ignores it.

    The shared pieces - a section name, the content string, each op's own
    description - sit in `$defs` and the branches carry local `$ref`s, which
    the converter does resolve. That keeps a pinned name list, which can be
    long and appears in every branch's `section`, written exactly once rather
    than repeated per branch.

    `section_names` is nothing the node currently populates - there is no
    registry of known names anymore, so every call site passes None and the
    schema accepts any section name. The parameter stays because pinning is a
    generically useful thing a schema can do, independent of whether anything
    in this file currently asks for it.
    """
    names = [n for n in (section_names or []) if n]
    name = {"type": "string", "minLength": 1}
    if names:
        name["enum"] = names

    defs = {
        "name": name,
        "content": {
            "type": "string",
            "minLength": 1,
            "description": _CONTENT_DESCRIPTION,
        },
        **{f"op_{op}": {"const": op, "description": description}
           for op, description in _OP_DESCRIPTIONS.items()},
    }
    NAME = {"$ref": "#/$defs/name"}
    CONTENT = {"$ref": "#/$defs/content"}

    def operation(title, op, properties):
        """One branch: `section` and `op`, plus exactly the fields it accepts.

        Everything a branch names is required and nothing else is allowed, so
        each valid entry matches exactly one branch and the oneOf stays sound.
        """
        return {
            "title": title,
            "type": "object",
            "required": ["section", "op", *properties],
            "additionalProperties": False,
            "properties": {
                "section": NAME,
                "op": {"$ref": f"#/$defs/op_{op}"},
                **properties,
            },
        }

    branches = [
        operation("Add a new section", "add", {
            "position": {"type": "integer", "description": _POSITION_DESCRIPTION},
            "content": CONTENT,
        }),
        operation("Change an existing section's content", "modify", {"content": CONTENT}),
        operation("Remove an existing section", "delete", {}),
    ]

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Prompt operations",
        "description": "Operations applied in order to a prompt's named sections.",
        "type": "array",
        "minItems": 1,
        "$defs": defs,
        "items": {"oneOf": branches},
    }


def schema_json(section_names=None, indent=2):
    return json.dumps(build_schema(section_names), indent=indent)


def key_of(name):
    """The identity of a section: names match case- and whitespace-insensitively.

    A model that writes "Style" on one turn and "style" on the next means the
    same section both times, and an add that silently created a near-duplicate
    would be the worst possible reading of that.
    """
    return " ".join(str(name).split()).lower()


def _coerce_op(value):
    """The operation name, or None if it is not exactly one this understands."""
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    return lowered if lowered in OPS else None


def _coerce_position(value):
    """`value` as an integer position, or None if it plainly is not one.

    A numeral string ("2") is accepted for the same reason `content` tolerates
    a stray int or list: a structured-output model that gets the JSON type
    wrong on an otherwise-clear value shouldn't lose the whole operation over
    it. `bool` is excluded even though it is an int subclass in Python, since
    True/False are never meaningful positions.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _coerce_content(value):
    """Section content from whatever the value happened to be, or None.

    None comes back for null and for anything that renders down to nothing.
    Callers treat that as invalid input, never as a deletion: removing a
    section is something a document has to ask for by name, with `op: delete`.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        parts = [_coerce_content(v) for v in value]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False) if value else None
    return None


def _parse_entry(entry, index, errors):
    """One array element as a single operation dict, or None if it does not hold up.

    An operation is always returned as {"op", "name", "content", "position"},
    with the fields an op does not use left None - so every caller downstream
    can read all four keys without checking which op it is looking at first.
    """
    where = f"[{index}]"
    if not isinstance(entry, dict):
        errors.append(f"{where} is {type(entry).__name__}, expected an object")
        return None

    name = entry.get("section")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{where}: 'section' must name a section")
        return None
    name = name.strip()
    where = f"{where} '{name}'"

    op = _coerce_op(entry.get("op"))
    if op is None:
        errors.append(f"{where}: 'op' must be one of {', '.join(OPS)}, got {entry.get('op')!r}")
        return None

    if "position" in entry and op != "add":
        errors.append(f"{where}: '{op}' ignores 'position' - only 'add' takes one")
    if "content" in entry and op == "delete":
        errors.append(f"{where}: 'delete' ignores 'content'")

    if op == "add":
        position = _coerce_position(entry.get("position"))
        if position is None:
            errors.append(f"{where}: 'add' needs an integer 'position'")
            return None
        content = _coerce_content(entry.get("content"))
        if content is None:
            errors.append(f"{where}: 'add' needs non-empty 'content'")
            return None
        return {"op": "add", "name": name, "content": content, "position": position}

    if op == "modify":
        content = _coerce_content(entry.get("content"))
        if content is None:
            errors.append(
                f"{where}: 'modify' needs non-empty 'content'"
                + (f' - to remove the section instead, use {{"section": "{name}", "op": "delete"}}'
                   if "content" in entry else "")
            )
            return None
        return {"op": "modify", "name": name, "content": content, "position": None}

    # delete
    return {"op": "delete", "name": name, "content": None, "position": None}


def parse_document(raw):
    """(operations, errors) for a document given as JSON text, bytes or a list.

    Never raises: errors come back as a list so the caller decides between
    failing the run and carrying on with the prompt it already had. A partial
    parse is still worth having - a malformed third entry should not cost you
    the first two.
    """
    errors = []
    document = raw
    if isinstance(document, (bytes, bytearray)):
        document = document.decode("utf-8", "replace")
    if isinstance(document, str):
        text = document.strip()
        if not text:
            return [], ["the document is empty"]
        try:
            document = json.loads(text)
        except json.JSONDecodeError as e:
            return [], [f"not valid JSON - {e}"]

    if not isinstance(document, list):
        return [], [f"the document is {type(document).__name__}, expected a JSON array"]

    operations = []
    for index, entry in enumerate(document):
        operation = _parse_entry(entry, index, errors)
        if operation is not None:
            operations.append(operation)
    return operations, errors


def _index_of(sections, name):
    wanted = key_of(name)
    return next((i for i, s in enumerate(sections) if key_of(s["name"]) == wanted), None)


def _resolve_position(position, count):
    """Where `add` inserts, for a prompt currently holding `count` sections.

    -1 and `count` both mean "append at the end" - -1 as the explicit end
    sentinel the schema documents, `count` because inserting before index
    `count` is the same operation for an index that otherwise runs 0..count.
    Anything in between inserts before that index. Anything outside
    [-1, count] does not resolve against the prompt as it stands, so it clamps
    to whichever end it overshot: a position under -1 lands at the beginning,
    one over `count` lands at the end. The document asked to be somewhere
    specific and missed; the closest real position is a better answer than
    dropping the operation over it.

    ::

        count=3, valid indices 0..3 (3 == append)
        position -5 -> 0   (undershot -1, clamps to the start)
        position -1 -> 3   (the end sentinel)
        position  0 -> 0
        position  2 -> 2
        position  3 -> 3   (== count, append)
        position  9 -> 3   (overshot count, clamps to the end)
    """
    if position < -1:
        return 0
    if position == -1 or position > count:
        return count
    return position


def merge(current, operations):
    """(sections, changes, errors) after applying `operations`, in order, to `current`.

    Every operation lands on the standing prompt in place - there is no
    "replace everything" reading of a document here. add inserts a section
    that must not already exist, at the position it names. modify changes an
    existing section's content without moving it. delete removes an existing
    section. Each of the three has exactly one legal precondition, and an
    operation that does not meet it is reported and skipped rather than
    reinterpreted as one of the others - a model that sends `add` for a
    section that turns out to already exist has a stale view of the prompt,
    and silently turning that into a modify would hide that from it.

    Any section name is accepted - there is no registry to check it against.
    The order sections end up in is nothing this function manages either: it
    is whatever `add`'s positions and the standing order already produce, so
    the first document that ever builds a prompt from nothing is what
    establishes its order, and everything after only changes that through an
    explicit operation.
    """
    sections = [dict(s) for s in current]
    changes = {"added": [], "modified": [], "removed": []}
    errors = []

    for operation in operations:
        name, op = operation["name"], operation["op"]
        at = _index_of(sections, name)

        if op == "add":
            if at is not None:
                errors.append(f"'{name}' already exists; use 'modify' to change it")
                continue
            index = _resolve_position(operation["position"], len(sections))
            sections.insert(index, {"name": name, "content": operation["content"]})
            changes["added"].append(name)
            continue

        if op == "modify":
            if at is None:
                errors.append(f"no section named '{name}' to modify")
                continue
            if sections[at]["content"] != operation["content"]:
                changes["modified"].append(sections[at]["name"])
            # The incoming spelling wins, so a label can be re-cased without
            # losing its place - modify never moves the section.
            sections[at] = {"name": name, "content": operation["content"]}
            continue

        # delete
        if at is None:
            errors.append(f"no section named '{name}' to delete")
            continue
        changes["removed"].append(sections[at]["name"])
        del sections[at]

    return sections, changes, errors


def render_section(name, content):
    return f"**{name}**: {str(content).strip()}"


def render(sections):
    """The prompt: one `**name**: content` paragraph per section, blank line between."""
    return "\n\n".join(render_section(s["name"], s["content"]) for s in sections)


def sections_dict(sections):
    """`sections` as {name: {"position": i, "content": ...}}, in render order.

    A lookup shape, not a replay shape: unlike state_json's list of `add`
    operations, this cannot be fed back into merge() as a document. It exists
    for callers that want a section's content and place by name in one map,
    without walking a list or parsing an operations array to find it.
    """
    return {s["name"]: {"position": i, "content": s["content"]} for i, s in enumerate(sections)}
