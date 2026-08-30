import json
import threading
import time

# history_id -> list of entries ({"index", "heading", "text", "time"}).
# Lives for as long as the ComfyUI server process does, which is what lets the
# viewer accumulate across separate queue runs (and survive a browser reload)
# the same way LlamaCppChatSession's _SESSIONS does.
_HISTORY_LOCK = threading.Lock()
_HISTORY = {}

MAX_ENTRIES_CEILING = 1000


def _resolve_history_id(history_id, unique_id):
    history_id = (history_id or "").strip()
    if history_id:
        return history_id
    return f"__node_{unique_id}"


def _snapshot(history_id):
    with _HISTORY_LOCK:
        return [dict(e) for e in _HISTORY.get(history_id, [])]


def _render_document(entries):
    """The accumulated entries as one markdown document.

    This is what makes the node 'extend' rather than just display: the growing
    document is an output, so it can be piped onward - back into an LLM as
    context, into a save-text node, into another viewer.
    """
    parts = []
    for entry in entries:
        heading = (entry.get("heading") or "").strip()
        text = entry.get("text") or ""
        parts.append(f"## {heading}\n\n{text}" if heading else text)
    return "\n\n".join(parts)


class MarkdownViewer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "markdown": ("STRING", {"default": "", "multiline": True}),
                "heading": (
                    "STRING",
                    {"default": "", "tooltip": "Optional label shown above this entry, and used as a '## heading' in the document output."},
                ),
                "history_id": (
                    "STRING",
                    {"default": "", "tooltip": "Leave blank to use a history unique to this node. Share the same id across nodes to append into one document."},
                ),
                "max_entries": (
                    "INT",
                    {"default": 50, "min": 0, "max": MAX_ENTRIES_CEILING, "tooltip": "0 = unlimited. Oldest entries are dropped first."},
                ),
                "append": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "On: each run adds an entry. Off: each run replaces the history with just this text."},
                ),
                "clear_first": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "Drop the existing history before adding this run's entry."},
                ),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("markdown", "document", "entry_count")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Display"
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Renders markdown in the node and keeps a running history of everything it has been "
        "given, so repeated runs build up a document instead of overwriting one another. "
        "Complements the chat nodes: wire an LLM reply in and watch the transcript grow. The "
        "accumulated 'document' output can be piped onward."
    )

    def run(
        self,
        markdown,
        heading,
        history_id,
        max_entries,
        append,
        clear_first,
        unique_id=None,
    ):
        hid = _resolve_history_id(history_id, unique_id)
        text = markdown or ""

        with _HISTORY_LOCK:
            if clear_first or not append:
                _HISTORY[hid] = []
            entries = _HISTORY.setdefault(hid, [])
            entries.append(
                {
                    "index": (entries[-1]["index"] + 1) if entries else 0,
                    "heading": (heading or "").strip(),
                    "text": text,
                    "time": time.time(),
                }
            )
            if max_entries > 0 and len(entries) > max_entries:
                del entries[: len(entries) - max_entries]
            snapshot = [dict(e) for e in entries]

        payload = json.dumps({"history_id": hid, "entries": snapshot})
        print(f"[MarkdownViewer:{hid}] {len(text)} chars, {len(snapshot)} entr(ies) in history")
        return {
            "ui": {"markdown_history": [payload]},
            "result": (text, _render_document(snapshot), len(snapshot)),
        }


# --- HTTP routes the node's UI uses -------------------------------------
# The frontend needs to read a history it didn't witness being produced (page
# reloaded, node re-opened) and to clear one without queueing a prompt, so both
# get a small endpoint rather than being smuggled through node execution.
def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:  # pragma: no cover - only if run outside ComfyUI
        print(f"[MarkdownViewer] routes not registered ({e}); the node still works, "
              "but Clear and reload-restore will be unavailable.")
        return

    routes = getattr(getattr(PromptServer, "instance", None), "routes", None)
    if routes is None:
        print("[MarkdownViewer] PromptServer not ready; routes not registered.")
        return

    @routes.get("/miseenplace/markdown_viewer/history")
    async def get_history(request):
        hid = request.query.get("history_id", "")
        if not hid:
            return web.json_response({"error": "history_id is required"}, status=400)
        return web.json_response({"history_id": hid, "entries": _snapshot(hid)})

    @routes.post("/miseenplace/markdown_viewer/clear")
    async def clear_history(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        hid = (body or {}).get("history_id", "")
        if not hid:
            return web.json_response({"error": "history_id is required"}, status=400)
        with _HISTORY_LOCK:
            _HISTORY.pop(hid, None)
        return web.json_response({"history_id": hid, "entries": []})


_register_routes()


NODE_CLASS_MAPPINGS = {"MarkdownViewer": MarkdownViewer}

NODE_DISPLAY_NAME_MAPPINGS = {"MarkdownViewer": "Markdown Viewer"}
