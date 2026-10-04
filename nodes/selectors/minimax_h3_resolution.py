# MiniMax H3 has no fixed bucket list: short side 768 (or ~3.7MP "2K"), VAE stride 32.
H3_RESOLUTIONS = [
    (672, 512), (928, 512), (1184, 512), (512, 512),
    (512, 672), (512, 928), (512, 1184),
    (864, 640), (1152, 640), (1504, 640), (640, 640),
    (640, 864), (640, 1152), (640, 1504),
    (1024, 768), (1376, 768), (1792, 768), (768, 768),
    (768, 1024), (768, 1376), (768, 1792),
    (2208, 1664), (2560, 1440), (2976, 1248), (1920, 1920),
    (1664, 2208), (1440, 2560), (1248, 2976),
]


class MiniMaxH3Resolution:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "width": ("INT", {"default": 1280, "min": 1, "max": 16384}),
                "height": ("INT", {"default": 720, "min": 1, "max": 16384}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/Selectors"

    def run(self, width, height):
        ratio = width / height

        def mismatch(r):
            return max(r[0] / r[1], ratio) / min(r[0] / r[1], ratio)

        pool = [r for r in H3_RESOLUTIONS if r[0] >= width and r[1] >= height]
        if pool:
            return min(pool, key=lambda r: r[0] * r[1] * mismatch(r))
        return min(H3_RESOLUTIONS, key=lambda r: mismatch(r) / (r[0] * r[1]))


NODE_CLASS_MAPPINGS = {"MiniMaxH3Resolution": MiniMaxH3Resolution}

NODE_DISPLAY_NAME_MAPPINGS = {"MiniMaxH3Resolution": "MiniMax H3 Resolution"}
