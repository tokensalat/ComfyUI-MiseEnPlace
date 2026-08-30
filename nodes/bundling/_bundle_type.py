"""
Shared BUNDLE type and helpers for the Bundler / Unbundler / Piercer nodes.

A bundle is a plain ordered dict of {name: value} built up by Bundler and
consumed by Unbundler/Piercer. This module is prefixed with "_" so the
package's node auto-discovery (see ../../__init__.py) skips importing it
directly as a node module.
"""

from comfy_api.latest import io

# Custom socket type so bundles can only be wired into bundle-aware nodes.
Bundle = io.Custom("ZERODRIFT_BUNDLE")


def parse_keys(keys: str) -> list:
    if not keys:
        return []
    return [k.strip() for k in keys.split(",")]
