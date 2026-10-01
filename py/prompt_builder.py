"""
ComfyUI-Minimax-H3-Promptor
This custom node for ComfyUI provides automation suite for generating MiniMax H3 prompts.

This integration script follows GPL-3.0 License.
"""

import re
from pathlib import Path
from .utils import log_info, log_error, log_debug


# Templates directory
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Leading phrases the vision analyzer tends to prepend to a description. When the
# tag is rendered as "<Picture 1> is {desc}" these would otherwise read as
# "<Picture 1> is The main subject is ..." (a duplicated intro).
_SUBJECT_INTRO_RE = re.compile(
    r"^(?:the\s+main\s+subject\s+(?:is|appears\s+(?:as|to\s+be))|"
    r"the\s+primary\s+subject\s+is|"
    r"the\s+subject\s+is|"
    r"this\s+(?:image|picture|photo|frame)\s+(?:shows|depicts|features)|"
    r"the\s+(?:image|picture|photo|frame)\s+(?:shows|depicts|features)|"
    r"this\s+is)\s+",
    re.IGNORECASE,
)


def _strip_subject_intro(desc: str) -> str:
    """Remove a leading 'The main subject is' style intro so the rendered
    '<Picture 1> is ...' line does not read '<Picture 1> is The main subject is ...'."""
    return _SUBJECT_INTRO_RE.sub("", desc.strip(), count=1)


class PromptBuilder:
    """Build system prompts and user messages for H3 prompt generation."""

    def __init__(self, templates_dir: str | Path | None = None):
        self.templates_dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR

    def build_system_prompt(
        self,
        task_type: str,
        template_override: str | None = None,
        duration: float = 5.0,
        target_model: str = "MiniMax H3",
    ) -> str:
        """
        Assemble the complete system prompt from template files.
        """
        parts = []

        # Select base template based on target model
        if target_model == "LTX 2.5":
            base = self._load_template("ltx25_system_base.txt")
        else:
            base = self._load_template("system_base.txt")
            
        if base:
            # Inject budget based on duration (approx 20-30 words per second)
            budget = int(duration * 25)
            budget_str = f"Word Budget Constraint: Approximately {budget} English words. Prioritize action over fluff."
            parts.append(f"{base}\n\n{budget_str}")
        else:
            parts.append(self._fallback_base())

        # Select task template based on target model
        if target_model == "LTX 2.5":
            task_template = self._load_template(f"ltx25_{task_type.lower()}.txt")
        else:
            if template_override and template_override != "default":
                task_template = self._load_template(template_override)
                if not task_template:
                    task_template = self._load_template(f"{task_type.lower()}.txt")
            else:
                task_template = self._load_template(f"{task_type.lower()}.txt")
        
        if task_template:
            parts.append(task_template)

        return "\n\n".join(parts)

    def generate_alignment_instruction(self, task_type: str, duration: float, image_count: int) -> str:
        """
        Produce mathematically precise FL2VA alignment strings.
        S.SS is floored based on the 17k+5 frame grid to ensure it doesn't fall off the edge.
        """
        if task_type != "FL2VA" or image_count < 2:
            return ""

        # Using the formula from minimax_plan.py
        s = "%.2f" % (int(round(max(0.0, float(duration)) * 10000)) // 100 / 100.0)
        
        return (f"How the reference pictures align with the target video — <Picture 1> "
                f"(from [Shot 1]) aligns with the 0.00-second mark of the target video; "
                f"<Picture 2> (from [Shot 2]) aligns with the {s}-second mark of the target video.")

    def generate_subject_definitions(self, image_count: int, has_video: bool, parsed_vision_dict: dict = None) -> str:
        """
        Programmatically generate exact MiniMax syntax for binding reference tokens.
        """
        lines = []
        if parsed_vision_dict:
            for i in range(image_count):
                key = f"<Picture {i+1}>"
                desc = parsed_vision_dict.get(key, "")
                if desc:
                    lines.append(f"{key} is {_strip_subject_intro(desc)}")
                else:
                    lines.append(f"{key} acts as a visual anchor.")
            if has_video:
                key = "<Video 1>"
                desc = parsed_vision_dict.get(key, "")
                if desc:
                    lines.append(f"{key} is the reference video: {desc}")
                else:
                    lines.append(f"{key} is the reference video.")
            return " ".join(lines)
        else:
            if image_count > 0:
                pictures = " and ".join(f"<Picture {i+1}>" for i in range(image_count))
                lines.append(f"<Subject 1> is the primary focus shown in {pictures}.")
                for i in range(image_count):
                    lines.append(f"<Picture {i+1}> acts as a visual anchor.")
            
            if has_video:
                lines.append("<Video 1> is the reference video: follow its motion and camera work exactly.")
            
            return " ".join(lines)

    def generate_summary(self, has_audio: bool = False) -> str:
        """
        One-line summary used by the MiniMax six-section backstop. Kept in sync with
        the retention block so we never claim audio reuse when no audio is attached.
        """
        return "reference generation + audio reuse" if has_audio else "reference generation"

    def generate_retention_analysis(self, image_count: int, has_video: bool, has_audio: bool) -> str:
        """
        Build the MiniMax `retention_analysis:` block listing ONLY the media that is
        actually attached. This prevents phantom tokens such as `<Picture 2>` or
        `<Audio 1>` from being injected when only a single image (or no audio) is used.
        """
        lines = []

        picture_tags = [f"<Picture {i + 1}>" for i in range(max(0, int(image_count)))]
        if picture_tags:
            lines.append(f"{'/'.join(picture_tags)}: fully_preserved")

        if has_video:
            lines.append("<Video 1>: fully_preserved")

        if has_audio:
            lines.append("<Audio 1>: fully_copy")

        return "\n".join(lines)

    def build_user_message(
        self,
        description: str,
        duration: float,
        task_type: str,
        vision_context: str = "",
        output_language: str = "English",
        image_count: int = 0,
        has_video: bool = False,
        target_model: str = "MiniMax H3",
    ) -> str:
        """
        Construct the main user instruction string dynamically based on the available inputs.
        """
        if target_model == "LTX 2.5":
            msg = f"Task: Generate an LTX-2.5 video prompt.\n\n"
        else:
            msg = f"Task: Generate a MiniMax {task_type} prompt.\n\n"
        
        if vision_context:
            msg += f"--- VISION ANALYSIS ---\nHere is the detailed analysis of the referenced images and videos for this generation:\n{vision_context}\n-----------------------\n\n"
            
        msg += f"Primary Target User Description:\n{description}\n\n"
        
        # Inject exact constraints
        msg += f"Constraint: The video will be {duration} seconds long (approx. {int(duration * 24)} frames). Pace the narrative accordingly.\n"
        
        # Inject tagging requirements
        available_tags = []
        for i in range(image_count):
            available_tags.append(f"<Picture {i+1}>")
        if has_video:
            available_tags.append("<Video 1>")
            
        if available_tags:
            msg += f"CRITICAL: You have the following media references available: {', '.join(available_tags)}.\n"
            if target_model == "LTX 2.5":
                msg += "Reference these naturally in your narrative to maintain visual continuity (e.g., 'matching the pose in <Picture 1>...').\n"
            else:
                msg += "You MUST physically insert these exact tags into your [Shot N] sentences to explicitly dictate which subject/motion appears in which shot. For example: `<Picture 1> enters the room, adopting the posture shown in <Video 1>`.\n"
        
        if output_language.lower() == "chinese":
            msg += "\n\nCRITICAL LANGUAGE CONSTRAINT:\nYou MUST write the ENTIRE OUTPUT PROMPT in Simplified Chinese (简体中文). Translate all technical film directions into equivalent Chinese terms."
        else:
            msg += "\n\nCRITICAL LANGUAGE CONSTRAINT:\nYou MUST write the ENTIRE OUTPUT PROMPT in English."

        return msg

    def get_available_templates(self) -> list[str]:
        templates = ["default"]
        if not self.templates_dir.exists():
            return templates
        for f in sorted(self.templates_dir.glob("*.txt")):
            if f.stem != "system_base":
                templates.append(f.name)
        return templates

    def _load_template(self, filename: str) -> str | None:
        path = self.templates_dir / filename
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except IOError as e:
            return None

    @staticmethod
    def _fallback_base() -> str:
        return "You are a professional MiniMax H3 prompt writer."
