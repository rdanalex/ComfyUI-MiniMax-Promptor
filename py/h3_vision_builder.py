"""
MiniMax H3 Vision Builder

Creates a `vision_context` JSON string from manual text inputs for images, videos, and audios.
This output is intentionally compatible with `H3_Promptor`'s expected `vision_context` format.
"""

import json
from comfy_api.latest import io

from .utils import log_info, log_error


class H3_Vision_Builder(io.ComfyNode):
    """
    MiniMax H3 Vision Builder

    Accepts manual text descriptions for images/videos/audios and emits a
    `vision_context` JSON string matching the analyzer's output format.
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3_Vision_Builder",
            display_name="MiniMax H3 Vision Builder",
            category="🧪AILab/🎬 MiniMax H3-Promptor",
            inputs=[
                io.Autogrow.Input("ref_images", optional=True,
                                  template=io.Autogrow.TemplatePrefix(
                                      input=io.String.Input("image_text", multiline=True, tooltip="Manual description for this image (will become <Picture N>)"),
                                      prefix="image_", min=0, max=9)),
                io.Autogrow.Input("ref_videos", optional=True,
                                  template=io.Autogrow.TemplatePrefix(
                                      input=io.String.Input("video_text", multiline=True, tooltip="Manual description for this video (will become <Video N>)"),
                                      prefix="video_", min=0, max=3)),
                io.Autogrow.Input("ref_audios", optional=True,
                                  template=io.Autogrow.TemplatePrefix(
                                      input=io.String.Input("audio_text", multiline=True, tooltip="Manual description for this audio (will become <Audio N>)"),
                                      prefix="audio_", min=0, max=3)),
                io.String.Input("global_vibe", multiline=True, default="", optional=True, tooltip="Optional synthesized Global_Vibe string."),
            ],
            outputs=[
                io.String.Output("vision_context", display_name="vision_context")
            ],
        )

    @classmethod
    def execute(
        cls,
        ref_images: io.Autogrow.Type = None,
        ref_videos: io.Autogrow.Type = None,
        ref_audios: io.Autogrow.Type = None,
        global_vibe: str = "",
    ) -> io.NodeOutput:
        try:
            def _get_iterable(media_input):
                if not media_input:
                    return []
                if isinstance(media_input, dict):
                    return media_input.values()
                if isinstance(media_input, (list, tuple)):
                    return media_input
                return [media_input]

            final_dict = {}
            media_keys = []

            # Images
            img_index = 1
            for txt in _get_iterable(ref_images):
                if txt is not None and str(txt).strip() != "":
                    key = f"<Picture {img_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    img_index += 1

            # Videos
            vid_index = 1
            for txt in _get_iterable(ref_videos):
                if txt is not None and str(txt).strip() != "":
                    key = f"<Video {vid_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    vid_index += 1

            # Audios
            aud_index = 1
            for txt in _get_iterable(ref_audios):
                if txt is not None and str(txt).strip() != "":
                    key = f"<Audio {aud_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    aud_index += 1

            if global_vibe and str(global_vibe).strip() != "":
                final_dict["Global_Vibe"] = str(global_vibe).strip()

            # Always include media keys to match analyzer behavior
            final_dict["_media_keys"] = media_keys

            # If no media and no global vibe, return empty dict
            if not media_keys and ("Global_Vibe" not in final_dict or not final_dict.get("Global_Vibe")):
                return io.NodeOutput("{}")

            final_output = json.dumps(final_dict, indent=4, ensure_ascii=False)
            log_info("H3_Vision_Builder: built vision_context")
            return io.NodeOutput(final_output)

        except Exception as e:
            log_error(str(e))
            return io.NodeOutput(f"[Builder Exception]: {str(e)}")


NODE_CLASS_MAPPINGS = {
    "H3_Vision_Builder": H3_Vision_Builder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3_Vision_Builder": "MiniMax H3 Vision Builder",
}
