"""
Shared storage for the Buffer Read / Buffer Write pair.

A feedback loop in a DAG-only graph can't be a real cycle, so the loop is
carried across separate queue runs instead: Buffer Read hands out whatever was
last stored (or `default`, the first time) and a handle - a plain string -
identifying where; Buffer Write, given that handle, stores its `value` there
for the *next* run to see. Wiring the handle forward (Read -> ... -> Write)
keeps the graph acyclic while still tying a specific Read to a specific Write.
Being a plain string, it can also just be typed into both nodes by hand
instead of wired, like a sender/receiver pair's name - either way, no file on
disk. This module is prefixed with "_" so node auto-discovery (see
../../__init__.py) skips importing it directly as a node module.
"""

import threading

_LOCK = threading.Lock()
# key -> {"value": Any, "revision": int}. Lives as long as the ComfyUI server
# process does - the same arrangement PromptBuilder's _STATE uses - which is
# what lets Buffer Write's value from one queue run reach Buffer Read on the
# next.
_STATE = {}


def read(key, default):
    with _LOCK:
        entry = _STATE.get(key)
        if entry is None:
            return default, 0
        return entry["value"], entry["revision"]


def write(key, value):
    with _LOCK:
        entry = _STATE.setdefault(key, {"value": None, "revision": 0})
        entry["value"] = value
        entry["revision"] += 1
        return entry["revision"]


def clear(key):
    with _LOCK:
        _STATE.pop(key, None)
