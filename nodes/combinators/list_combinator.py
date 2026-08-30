class ListCombinator:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "list_a": ("STRING", {"default": "euler, dpmpp_2m"}),
                "list_b": ("STRING", {"default": "normal, karras"}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("combinations", "total")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Combinators"

    def run(self, list_a, list_b):
        # Parse lists
        list_a_items = [item.strip() for item in list_a.split(",") if item.strip()]
        list_b_items = [item.strip() for item in list_b.split(",") if item.strip()]

        # Create Cartesian product
        combos = [(a, b) for a in list_a_items for b in list_b_items]
        total = len(combos)

        # Format combinations as string
        combinations = "|".join([f"{a},{b}" for a, b in combos])

        status = f"Generated {total} combinations"
        print(status)

        return (combinations, total)


NODE_CLASS_MAPPINGS = {"ListCombinator": ListCombinator}

NODE_DISPLAY_NAME_MAPPINGS = {"ListCombinator": "List Combinator"}
