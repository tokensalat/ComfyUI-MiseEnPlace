"""
ComfyUI-MiseEnPlace
Personal collection of custom ComfyUI nodes — MiseEnPlace edition.

Nodes are auto-discovered from category subdirectories.
"""

import importlib
import pkgutil
from pathlib import Path

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Get the nodes directory path
nodes_dir = Path(__file__).parent / "nodes"

# Iterate through subdirectories (categories)
for category_path in sorted(nodes_dir.iterdir()):
    if category_path.is_dir() and not category_path.name.startswith("_"):
        # Find all Python modules in this category
        for importer, modname, ispkg in pkgutil.iter_modules([str(category_path)]):
            # Skip private modules (starting with _)
            if modname.startswith("_"):
                continue

            try:
                # Dynamically import the module
                module_path = f".nodes.{category_path.name}.{modname}"
                module = importlib.import_module(module_path, package=__name__)

                # Collect NODE_CLASS_MAPPINGS if it exists
                if hasattr(module, "NODE_CLASS_MAPPINGS"):
                    NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)

                # Collect NODE_DISPLAY_NAME_MAPPINGS if it exists
                if hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS"):
                    NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)
            except Exception as e:
                print(f"Failed to load node from {category_path.name}/{modname}: {e}")

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
__version__ = "0.1.0"
__author__ = "tokensalat"
