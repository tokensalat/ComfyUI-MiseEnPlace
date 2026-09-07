class IndexCombinator:
    """Flattens two independent loops (e.g. two PatternSweep/PatternSweepConfig pairs) into one
    linear index_in, the way ListCombinator does for two string lists but for index-driven
    loopers instead: index_b is the fast-changing one, index_a advances every total_b steps -
    same nesting as `for a in range(total_a): for b in range(total_b): ...`.

    Wire total_a/total_b from each sweep's PatternSweepConfig.total, index_in from a single INT
    primitive set to "increment", total to that primitive's max, and index_a/index_b straight
    into each PatternSweep's own index_in. For a third dimension, feed this node's own `total`
    as another combinator's total_a."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "total_a": ("INT", {"default": 1, "min": 1}),
                "total_b": ("INT", {"default": 1, "min": 1}),
                "index_in": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "STRING")
    RETURN_NAMES = ("index_a", "index_b", "total", "status")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Combinators"

    def run(self, total_a, total_b, index_in):
        total = total_a * total_b
        k = max(0, min(index_in, total - 1))
        index_a = k // total_b
        index_b = k % total_b

        status = f"[{k + 1} / {total}] a={index_a}, b={index_b}"
        print(f"[IndexCombinator] {status}")
        return (index_a, index_b, total, status)


NODE_CLASS_MAPPINGS = {"IndexCombinator": IndexCombinator}
NODE_DISPLAY_NAME_MAPPINGS = {"IndexCombinator": "Index Combinator"}
