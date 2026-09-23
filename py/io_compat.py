"""
ComfyUI-Minimax-H3-Promptor
Small compatibility helpers for the ComfyUI v3 node API.

``io.Autogrow`` (the self-growing group input) only exists on newer ComfyUI builds.
On older builds we fall back to a fixed set of optional single-slot inputs so the nodes
still load and execute; the slot values are re-collected in ``execute()``.
"""

from comfy_api.latest import io


# io.Autogrow.Type (a dict of the live slots) on new builds, hardcoded containers on old ones.
AUTOGROW_TYPE = getattr(getattr(io, "Autogrow", None), "Type", list)

# io.Video exists on newer builds, older ones fall back to a generic socket.
VIDEO_INPUT_TYPE = getattr(io, "Video", getattr(io, "AnyType", io.Image))

# Sentinel for "this ComfyUI build supports the v3 io.Autogrow API".
HAS_AUTOGROW = hasattr(io, "Autogrow")


def template_input(media_kind: str, base_id: str = None, tooltip: str = None):
    """A fresh socket/widget template for one media kind."""
    if media_kind == "image":
        return io.Image.Input(base_id or "image", tooltip=tooltip or "Reference image")
    if media_kind == "video":
        return VIDEO_INPUT_TYPE.Input(base_id or "video", tooltip=tooltip or "Reference video")
    if media_kind == "audio":
        return io.Audio.Input(base_id or "audio", tooltip=tooltip or "Reference audio")
    return io.String.Input(base_id or "text", multiline=True, tooltip=tooltip)


def growing_inputs(group_id: str, media_kind: str, prefix: str, min_slots: int = 0,
                   max_slots: int = 9, base_id: str = None, tooltip: str = None):
    """
    Inputs for one growable media group.

    New builds: a single ``io.Autogrow`` group input (``group_id``) that grows on demand.
    Old builds: ``max_slots`` optional single-slot inputs named ``{prefix}0..{max-1}``.
    """
    if HAS_AUTOGROW:
        return [io.Autogrow.Input(
            group_id,
            optional=True,
            template=io.Autogrow.TemplatePrefix(
                input=template_input(media_kind, base_id, tooltip),
                prefix=prefix, min=min_slots, max=max_slots),
        )]

    slots = []
    # 0-based slot ids so the legacy fallback matches the autogrow socket names
    # (image_0 ... image_{max-1}) and the node's image_N_text outputs.
    for slot in range(max_slots):
        slot_input = template_input(media_kind, base_id, tooltip)
        slot_input.id = f"{prefix}{slot}"
        slot_input.optional = True
        slots.append(slot_input)
    return slots


def collect_slots(group_value, legacy_slots: dict, prefix: str, max_slots: int) -> list:
    """
    Normalize whatever the frontend delivered into a plain ordered list of values.

    Handles both an autogrow container (dict/list on new builds) and the fixed
    ``{prefix}0..{max-1}`` inputs of the legacy fallback.
    """
    if group_value:
        if isinstance(group_value, dict):
            return [value for value in group_value.values() if value is not None]
        if isinstance(group_value, (list, tuple)):
            return [value for value in group_value if value is not None]
        return [group_value]

    collected = []
    for slot in range(max_slots):
        value = legacy_slots.get(f"{prefix}{slot}")
        if value is not None:
            collected.append(value)
    return collected
