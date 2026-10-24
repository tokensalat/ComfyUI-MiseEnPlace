"""
Shared BUNDLE type and helpers for the Bundler / Unbundler / Piercer nodes.

A bundle is a plain ordered dict of {name: value} built up by Bundler and
consumed by Unbundler/Piercer. This module is prefixed with "_" so the
package's node auto-discovery (see ../../__init__.py) skips importing it
directly as a node module.
"""

from comfy_api.latest import io

# Custom socket type so bundles can only be wired into bundle-aware nodes.
Bundle = io.Custom("MISEENPLACE_BUNDLE")


def parse_keys(keys) -> list:
    # A subgraph-exposed "keys" input left unconnected outside gets promoted to
    # a widget by the frontend, and that promotion can default to a bare 0
    # instead of "". A real "keys" value is always a str, so anything else is
    # that corruption, not user intent - treat it the same as no keys rather
    # than str()-ing it into a bogus single key named "0".
    if not isinstance(keys, str):
        return []
    keys = keys.strip()
    if not keys:
        return []
    return [k.strip() for k in keys.split(",")]
