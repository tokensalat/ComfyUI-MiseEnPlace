import json
import requests
import base64
import numpy as np
from PIL import Image
import io

from ._llm_config import CONFIG_INPUT, field, merge_settings
from ._llm_schema import json_schema_input, parse_json_schema
from ._llm_text import EXTRACT_PATTERN_DEFAULT, extract_from_reply, extract_pattern_input


class LlamaCppClient:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "url": field("url"),
                "timeout": field("timeout"),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "temperature": field("temperature"),
                "repeat_penalty": field("repeat_penalty"),
                "top_k": field("top_k"),
                "top_p": field("top_p"),
                "min_p": field("min_p"),
                "presence_penalty": field("presence_penalty"),
                "min_image_tokens": field("min_image_tokens"),
                "max_image_tokens": field("max_image_tokens"),
                "do_image_splitting": field("do_image_splitting"),
                "seed": field("seed"),
                "force_resend": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "image": ("IMAGE",),
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                # Last, and a link-only socket, so it takes no widgets_values
                # slot and existing workflows load unchanged.
                "config": CONFIG_INPUT,
                # After config so it is the last *widget*, for the same reason.
                "extract_pattern": extract_pattern_input(),
                # New, so it goes after extract_pattern - the current last
                # widget - to keep every existing saved widgets_values index
                # pointing at what it always did.
                "json_schema": json_schema_input(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    # "extracted" is appended rather than slotted in after "response" so that
    # existing links to "debug" keep their slot index.
    RETURN_NAMES = ("response", "debug", "extracted")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/LLM"

    @classmethod
    def IS_CHANGED(s, **kwargs):
        if kwargs.get("force_resend", False):
            # Return a unique value to force re-execution
            import time

            return float(time.time())
        return ""

    def _image_to_base64(self, image_tensor):
        """Convert ComfyUI image tensor to base64 string."""
        try:
            # ComfyUI images are typically in the format [batch, height, width, channels]
            # Convert from tensor to PIL Image
            if isinstance(image_tensor, np.ndarray):
                img_array = image_tensor
            else:
                img_array = image_tensor.cpu().numpy()

            # Take first image if batch
            if len(img_array.shape) == 4:
                img_array = img_array[0]

            # Convert from 0-1 float to 0-255 uint8
            if img_array.dtype == np.float32 or img_array.dtype == np.float64:
                img_array = (img_array * 255).astype(np.uint8)

            # Create PIL Image
            pil_image = Image.fromarray(img_array)

            # Convert to base64
            buffered = io.BytesIO()
            pil_image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            return img_str
        except Exception as e:
            print(f"Error converting image to base64: {e}")
            return None

    def run(
        self,
        url,
        prompt,
        temperature,
        repeat_penalty,
        top_k,
        top_p,
        min_p,
        presence_penalty,
        min_image_tokens,
        max_image_tokens,
        do_image_splitting,
        seed,
        timeout,
        force_resend,
        system_prompt="",
        image=None,
        config=None,
        # Mirrors the widget default so an api-format prompt that omits the
        # input behaves like a freshly added node rather than silently
        # skipping extraction.
        extract_pattern=EXTRACT_PATTERN_DEFAULT,
        json_schema="",
    ):
        # A connected Llama-cpp Config overrides the widgets it covers; with
        # nothing connected this is just the local values. Prompts are never
        # part of it - see nodes/llm/_llm_config.py.
        settings = merge_settings(
            config,
            {
                "url": url,
                "timeout": timeout,
                "temperature": temperature,
                "repeat_penalty": repeat_penalty,
                "top_k": top_k,
                "top_p": top_p,
                "min_p": min_p,
                "presence_penalty": presence_penalty,
                "min_image_tokens": min_image_tokens,
                "max_image_tokens": max_image_tokens,
                "do_image_splitting": do_image_splitting,
                "seed": seed,
            },
        )
        url = settings["url"]
        timeout = settings["timeout"]
        seed = settings["seed"]

        try:
            # Build messages array for chat completions API
            messages = []

            # Add system prompt if provided
            if system_prompt and system_prompt.strip():
                messages.append({"role": "system", "content": system_prompt})

            # Add user message with prompt
            user_message = {"role": "user", "content": prompt}

            # Add image if provided (for multimodal models)
            if image is not None:
                img_base64 = self._image_to_base64(image)
                if img_base64:
                    # OpenAI-compatible format for vision models
                    user_message["content"] = [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                        },
                    ]

            messages.append(user_message)

            # Build the request payload for chat completions API
            payload = {
                "messages": messages,
                "temperature": settings["temperature"],
                "repeat_penalty": settings["repeat_penalty"],
                "top_k": settings["top_k"],
                "top_p": settings["top_p"],
                "min_p": settings["min_p"],
                "presence_penalty": settings["presence_penalty"],
                "min_image_tokens": settings["min_image_tokens"],
                "max_image_tokens": settings["max_image_tokens"],
                "do_image_splitting": settings["do_image_splitting"],
                "stream": False,
            }

            # Add seed if not -1
            if seed != -1:
                payload["seed"] = seed

            # Constrain the reply to a schema, if one is connected. The server
            # does the schema -> grammar conversion; see _llm_schema.py.
            format_block = parse_json_schema(json_schema, "[LlamaCppClient] ")
            if format_block:
                payload["response_format"] = format_block

            # Make the HTTP request
            print(f"Sending request to llama-cpp server at {url}")
            print(f"Prompt length: {len(prompt)} chars")

            headers = {"Content-Type": "application/json"}
            response = requests.post(
                url, json=payload, headers=headers, timeout=timeout
            )

            # Check if request was successful
            if response.status_code != 200:
                error_detail = response.text
                error_msg = f"Server returned error status {response.status_code}: {error_detail}"
                print(error_msg)
                raise Exception(error_msg)

            # Parse the response
            result = response.json()

            # Store full response for debug output
            debug_output = json.dumps(result, indent=2)

            # Extract the generated text from chat completions response
            generated_text = ""
            if "choices" in result and len(result["choices"]) > 0:
                choice = result["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    generated_text = choice["message"]["content"]
                elif "text" in choice:
                    generated_text = choice["text"]
            elif "content" in result:
                # Fallback for non-chat endpoints
                generated_text = result["content"]
            elif "response" in result:
                generated_text = result["response"]
            elif "text" in result:
                generated_text = result["text"]
            else:
                # Fallback: return the entire JSON as string
                generated_text = debug_output

            extracted = extract_from_reply(generated_text, extract_pattern, "[LlamaCppClient] ")
            print(f"Received response: {len(generated_text)} chars")
            return (generated_text, debug_output, extracted)

        except requests.exceptions.RequestException as e:
            error_msg = f"HTTP request failed: {str(e)}"
            print(error_msg)
            return (error_msg, error_msg, "")
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse JSON response: {str(e)}"
            print(error_msg)
            return (error_msg, error_msg, "")
        except Exception as e:
            error_msg = f"Error communicating with llama-cpp server: {str(e)}"
            print(error_msg)
            return (error_msg, error_msg, "")


NODE_CLASS_MAPPINGS = {"LlamaCppClient": LlamaCppClient}

NODE_DISPLAY_NAME_MAPPINGS = {"LlamaCppClient": "Llama-cpp Client"}
