_DOC = """Prompt Builder: a sectioned prompt, built from JSON and kept version by version.

The node's `schema` output is a JSON Schema for the document it reads, ready to
constrain the model that writes it. It is not transcribed here - this docstring
is assembled at import from `_prompt_schema.build_schema()`, so what you are
reading is the schema the node emits rather than a copy that agrees with it
today.

__SCHEMA__

The document is a bare array of operations, applied to the standing prompt in
order. There is no "replace everything" shape: every document edits whatever
prompt already exists. To start over, turn on the node's own `reset` input and
send a document that adds back every section you want - `reset` empties the
standing prompt before the document runs, so starting fresh is something you
ask the node for directly, not something implied by what a document happens to
contain.

The `state_json` output is that same idea from the other side: the whole
standing prompt, expressed as one `add` per section at its current position.
Feeding it back in without `reset` fails every entry with "already exists",
because from the document's point of view every one of those sections is
already there - `state_json` is meant to be replayed against an empty prompt,
paired with `reset`, not merged into the one it came from.

`sections_json` is a third shape for the same prompt, and the one to reach for
if you just want to read it rather than replay it: a plain object keyed by
section name, each value carrying its position and content -

    {"style": {"position": 0, "content": "documentary photograph"},
     "subject": {"position": 1, "content": "a fishmonger in a yellow apron"}}

`position` here is only where the section currently sits, not an instruction;
unlike `state_json`, feeding this back into anything is not the point, and
there is no operation that reads it.

add
    Inserts a new section. `content` is its text, `position` says where. The
    section must not already exist - a model that sends `add` for something
    that turns out to be there already has a stale view of the prompt, and it
    is reported rather than quietly treated as an edit.
modify
    Changes an existing section's `content` in place. Never repositions it -
    only `add` can say where something goes, so a section stays exactly where
    it was put until an `add` elsewhere changes what the prompt looks like
    around it.
delete
    Removes an existing section. Takes nothing but the name.

A worked document, applied to an empty prompt:

    [
      {"section": "subject", "op": "add", "position": 0,
       "content": "a lighthouse keeper reading by lamplight"},
      {"section": "style", "op": "add", "position": 1,
       "content": "35mm film photograph, soft grain"},
      {"section": "lighting", "op": "add", "position": 2,
       "content": "warm practical light, deep shadows"}
    ]

renders:

    **subject**: a lighthouse keeper reading by lamplight

    **style**: 35mm film photograph, soft grain

    **lighting**: warm practical light, deep shadows

Applied to that, a second document:

    [
      {"section": "style", "op": "modify",
       "content": "charcoal sketch on grey paper"},
      {"section": "mood", "op": "add", "position": 1,
       "content": "still, held breath"},
      {"section": "lighting", "op": "delete"}
    ]

renders:

    **subject**: a lighthouse keeper reading by lamplight

    **mood**: still, held breath

    **style**: charcoal sketch on grey paper

- style keeps its content but not its old index, because mood was inserted
  ahead of it; mood lands at position 1, between subject and style; lighting is
  gone. The version records that as added=[mood], modified=[style],
  removed=[lighting].

Any section name is accepted - there is no registry of known names to check
one against, and no step anywhere that sorts sections toward some configured
order. The order a prompt's sections come out in is nothing this node manages;
it is exactly what the operations produced. The first document that ever
builds a prompt from nothing - a run of `add`s against an empty standing
prompt - is what establishes that order, because there is nothing to arrange
until then. Everything after only changes it through an explicit operation:
a new `add` inserts at the position it names, and an existing section's place
holds until something explicitly moves it - which, since `modify` never
repositions, means deleting it and adding it back in the same document.
Nothing reshuffles a section that a document did not touch.

`content` is always a non-empty string. There is no falsy value that means
"delete" - a section comes out only when a document asks for it by name with
`op: delete`, because a value that arrives null or empty is a generation that
went wrong far more often than a deletion anybody meant, so it is reported and
nothing is removed.
"""

import json
import threading
import time

from comfy_api.latest import io

from ._prompt_schema import (
    key_of,
    merge,
    parse_document,
    render,
    schema_json,
    sections_dict,
)

# prompt_id -> {"revision", "sections", "history"}. Lives as long as the ComfyUI
# server process does, which is what lets an edit run land on the prompt an
# earlier run built, across separate queue runs and browser reloads - the same
# arrangement MarkdownViewer's _HISTORY uses.
_STATE_LOCK = threading.Lock()
_STATE = {}

MAX_HISTORY_CEILING = 500


def _indented(text, spaces=4):
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


# The docstring is assembled rather than written, so the schema in it is the
# schema, not a transcription that has to be kept honest by hand. A plain
# replace, not str.format: the prose is full of JSON braces and every one of
# them would otherwise need escaping.
__doc__ = _DOC.replace("__SCHEMA__", _indented(schema_json()))

DEFAULT_DOCUMENT = json.dumps(
    [
        {
            "section": "subject",
            "op": "add",
            "position": 0,
            "content": "a lighthouse keeper reading by lamplight",
        },
        {
            "section": "style",
            "op": "add",
            "position": 1,
            "content": "35mm film photograph, soft grain",
        },
        {
            "section": "lighting",
            "op": "add",
            "position": 2,
            "content": "warm practical light, deep shadows",
        },
    ],
    indent=2,
)


def _resolve_prompt_id(prompt_id, unique_id):
    prompt_id = (prompt_id or "").strip()
    return prompt_id or f"__node_{unique_id}"


def _new_state():
    return {"revision": 0, "sections": [], "history": []}


def _snapshot_locked(pid, state):
    """A deep-enough copy of one prompt's state to hand to JSON.

    Callers hold _STATE_LOCK - it is a plain Lock, so a public _snapshot() that
    took it again would deadlock anyone already inside the critical section.
    """
    if state is None:
        return {"prompt_id": pid, **_new_state()}
    return {
        "prompt_id": pid,
        "revision": state["revision"],
        "sections": [dict(s) for s in state["sections"]],
        "history": [
            {**v, "sections": [dict(s) for s in v["sections"]]}
            for v in state["history"]
        ],
    }


def _snapshot(pid):
    with _STATE_LOCK:
        return _snapshot_locked(pid, _STATE.get(pid))


def _record(state, sections, changes, note, max_history):
    """Append a version and return it.

    History is append-only: restoring an old version adds a new one rather than
    truncating, so nothing you have seen on the node can disappear from under
    you. That costs a little memory and buys a prompt you can always walk back.
    """
    state["revision"] += 1
    version = {
        "index": state["revision"],
        "time": time.time(),
        "note": note,
        "added": changes.get("added", []),
        "modified": changes.get("modified", []),
        "removed": changes.get("removed", []),
        "sections": [dict(s) for s in sections],
        "text": render(sections),
    }
    state["sections"] = [dict(s) for s in sections]
    state["history"].append(version)
    if max_history > 0 and len(state["history"]) > max_history:
        del state["history"][: len(state["history"]) - max_history]
    return version


def restore(pid, index):
    """Make version `index` of prompt `pid` current again; (payload, status).

    Recorded as a new version rather than by rewinding, so the history stays
    append-only and the trip back is itself part of the record. Kept out of the
    route handler so it is reachable without an HTTP server in front of it.
    """
    with _STATE_LOCK:
        state = _STATE.get(pid)
        if state is None:
            return {"error": f"no prompt state for '{pid}'"}, 404
        source = next((v for v in state["history"] if v["index"] == index), None)
        if source is None:
            return {"error": f"no version {index} in the history"}, 404
        if index == state["revision"]:
            return _snapshot_locked(pid, state), 200  # already there; nothing to record

        restored = [dict(s) for s in source["sections"]]
        before = {key_of(s["name"]) for s in state["sections"]}
        after = {key_of(s["name"]) for s in restored}
        changes = {
            "added": [s["name"] for s in restored if key_of(s["name"]) not in before],
            "modified": [s["name"] for s in restored if key_of(s["name"]) in before],
            "removed": [
                s["name"] for s in state["sections"] if key_of(s["name"]) not in after
            ],
        }
        # Unlimited history, because what the UI is showing must not shrink
        # under the very click that restores from it. max_history is enforced
        # on execute().
        _record(state, restored, changes, f"restored v{index}", 0)
        return _snapshot_locked(pid, state), 200


class PromptBuilder(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PromptBuilder",
            display_name="Prompt Builder",
            category="MiseEnPlace/Prompting",
            description=(
                "Builds a sectioned prompt from a JSON array of operations and keeps every "
                'version of it. Feed it [{"section": "style", "op": "add", "position": 0, '
                '"content": "..."}, ...] and each operation lands on the standing prompt in '
                "order: add inserts a new section at a position, modify changes an existing "
                "section's content without moving it, delete removes one. There is no "
                "'replace everything' shape - turn on 'reset' to start from empty. The "
                "'schema' output is the JSON Schema for that array, ready to constrain the "
                "model that writes it."
            ),
            inputs=[
                io.String.Input(
                    "prompt_json",
                    multiline=True,
                    default=DEFAULT_DOCUMENT,
                    tooltip='The document: a JSON array of {"section", "op", "content"/"position"} operations, applied in order to the standing prompt.',
                ),
                io.String.Input(
                    "prompt_id",
                    optional=True,
                    default="",
                    tooltip="Leave blank for a history unique to this node. Share the same id across nodes to build one prompt from several places.",
                ),
                io.Int.Input(
                    "max_history",
                    optional=True,
                    default=50,
                    min=0,
                    max=MAX_HISTORY_CEILING,
                    tooltip="0 = unlimited. Oldest versions are dropped first.",
                ),
                io.Boolean.Input(
                    "reset",
                    optional=True,
                    default=False,
                    tooltip="Discard the standing prompt and its history before applying this document. Pair with a document of 'add' operations to start a prompt from scratch.",
                ),
                io.Boolean.Input(
                    "strict",
                    optional=True,
                    default=False,
                    tooltip="Off: a malformed document is logged and the standing prompt is passed through unchanged. On: it fails the run instead.",
                ),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="state_json"),
                io.String.Output(display_name="schema"),
                io.Int.Output(display_name="version"),
                # Appended last, after version, so existing links to the four
                # outputs above keep the socket index they already have.
                io.String.Output(display_name="sections_json"),
            ],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, prompt_json="", prompt_id="", **kwargs):
        """Re-run whenever the stored prompt has moved, not just the inputs.

        Without this, restoring an old version from the node's UI and re-queueing
        an otherwise unchanged graph would be answered from cache with the
        superseded prompt - the one thing the history is there to prevent.
        """
        pid = _resolve_prompt_id(prompt_id, getattr(cls.hidden, "unique_id", None))
        with _STATE_LOCK:
            revision = _STATE.get(pid, {}).get("revision", 0)
        return f"{revision}:{json.dumps([prompt_json, kwargs], sort_keys=True, default=repr)}"

    @classmethod
    def execute(
        cls,
        prompt_json=DEFAULT_DOCUMENT,
        prompt_id="",
        max_history=50,
        reset=False,
        strict=False,
    ) -> io.NodeOutput:
        pid = _resolve_prompt_id(prompt_id, cls.hidden.unique_id)
        schema = schema_json()

        operations, errors = parse_document(prompt_json)

        with _STATE_LOCK:
            state = _STATE.setdefault(pid, _new_state())
            # Worked out before anything is written, so that `strict` can still
            # raise on an operation that only turns out to be impossible once it
            # meets the standing prompt - an add whose name is already there -
            # without having already spent a version on it.
            standing = [] if reset else state["sections"]
            if operations:
                sections, changes, merge_errors = merge(standing, operations)
                errors = errors + merge_errors
            else:
                sections = [dict(s) for s in standing]
                changes = None

            if strict and errors:
                # Leaving the `with` releases the lock; the state is as it was.
                raise ValueError(f"Prompt Builder [{pid}]: {'; '.join(errors)}")

            if reset:
                _STATE[pid] = state = _new_state()
            if operations:
                note = "update after reset" if reset else "update"
                version = _record(state, sections, changes, note, max_history)
            else:
                # Nothing usable came in. Re-render what is already there rather
                # than emitting an empty prompt: downstream nodes are better
                # served by the last good prompt than by nothing at all.
                state["sections"] = sections
                version = {
                    "index": state["revision"],
                    "text": render(sections),
                    "added": [],
                    "modified": [],
                    "removed": [],
                }
            snapshot = _snapshot_locked(pid, state)

        if errors:
            print(f"[PromptBuilder:{pid}] {'; '.join(errors)}")

        text = version["text"]
        # A sequence of `add`s, one per section at its current index. This is
        # the whole prompt, so replaying it against a non-empty standing prompt
        # would fail every entry with "already exists" - it is meant to be
        # paired with `reset`, the same way the old is_edit:false document was
        # implicitly a reset. Feeding it back without reset is a deliberate
        # error rather than a silent overwrite of state the caller may not have
        # meant to discard.
        state_json = json.dumps(
            [
                {
                    "section": s["name"],
                    "op": "add",
                    "position": i,
                    "content": s["content"],
                }
                for i, s in enumerate(snapshot["sections"])
            ],
            indent=2,
        )
        # A lookup shape rather than a replay shape - see sections_dict()'s
        # docstring. Position is just the section's current index, not
        # anything an `add` would need to reproduce it.
        sections_json = json.dumps(sections_dict(snapshot["sections"]), indent=2)

        touched = version["added"] + version["modified"] + version["removed"]
        print(
            f"[PromptBuilder:{pid}] v{snapshot['revision']} "
            f"{len(snapshot['sections'])} section(s)"
            + (f", touched {touched}" if touched else "")
        )
        return io.NodeOutput(
            text,
            state_json,
            schema,
            snapshot["revision"],
            sections_json,
            ui={"prompt_state": [json.dumps({**snapshot, "errors": errors})]},
        )


# --- HTTP routes the node's UI uses -------------------------------------
# The frontend reads state it never witnessed being produced (page reloaded,
# node re-opened) and restores an old version without queueing a prompt, so
# both get a small endpoint rather than being smuggled through node execution.
def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:  # pragma: no cover - only if run outside ComfyUI
        print(
            f"[PromptBuilder] routes not registered ({e}); the node still renders, "
            "but the history panel will be read-only and empty after a reload."
        )
        return

    routes = getattr(getattr(PromptServer, "instance", None), "routes", None)
    if routes is None:
        print("[PromptBuilder] PromptServer not ready; routes not registered.")
        return

    def _require_id(body):
        pid = (body or {}).get("prompt_id", "")
        return pid.strip() if isinstance(pid, str) else ""

    @routes.get("/miseenplace/prompt_builder/state")
    async def get_state(request):
        pid = request.query.get("prompt_id", "").strip()
        if not pid:
            return web.json_response({"error": "prompt_id is required"}, status=400)
        return web.json_response(_snapshot(pid))

    @routes.post("/miseenplace/prompt_builder/clear")
    async def clear_state(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        pid = _require_id(body)
        if not pid:
            return web.json_response({"error": "prompt_id is required"}, status=400)
        with _STATE_LOCK:
            _STATE.pop(pid, None)
        return web.json_response(_snapshot(pid))

    @routes.post("/miseenplace/prompt_builder/restore")
    async def restore_version(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        pid = _require_id(body)
        index = (body or {}).get("index")
        if not pid or not isinstance(index, int):
            return web.json_response(
                {"error": "prompt_id and an integer index are required"}, status=400
            )
        payload, status = restore(pid, index)
        return web.json_response(payload, status=status)


_register_routes()


NODE_CLASS_MAPPINGS = {"PromptBuilder": PromptBuilder}

NODE_DISPLAY_NAME_MAPPINGS = {"PromptBuilder": "Prompt Builder"}
