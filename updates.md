# ComfyUI-Minimax-H3-Promptor Update Log

---

## Release Notes: v1.2.0

### Per-Reference Text Outputs (no more JSON digging)
- **One output per slot**: `H3_Vision_Analyzer` now exposes a dedicated STRING output per reference: `global_vibe`, `image_0_text` … `image_2_text`, `video_0_text`, `audio_0_text` (names mirror the input sockets: `image_0` → `image_0_text`). Slots that are not connected return an empty string.
- **`vision_context` is untouched and still output #0**, so existing H3 workflows and `H3_Promptor` keep working exactly as before.
- ComfyUI's v3 schema has no dynamic-output support (there is no `io.Autogrow.Output`), so the per-slot ports are a small fixed set matching the 3 / 1 / 1 media limits (3 images + 1 video + 1 audio) instead of growing on demand.

### Instruction Profiles - the node now works for any target model (LTX 2.5 included)
- **Model agnostic by design**: all instructions moved into named *profiles* inside `vision_prompts.json` - `MiniMax H3` (the previous presets, unchanged) and `LTX 2.5` (shot / wardrobe / environment / camera / grade / atmosphere oriented, flowing present-tense prose, single continuous take).
- **New `instruction_profile` dropdown** selects the profile; add your own profiles to the JSON and they appear after a restart. `Profile Default` resolves to the first instruction of the selected profile.
- **New `global_audio_mode`** replaces the previously hard-coded audio instruction and brings real audio presets (`Music & Score`, `Dialogue & Vocals`, `Ambience & SFX`, …).
- `global_image_mode` / `global_video_mode` / `global_vibe_mode` now list the union of every profile's presets, and a preset missing from the active profile still resolves from the profile that defines it, so saved workflows never break.
- Old flat `vision_prompts.json` files (top-level `image_prompts` / `video_prompts`) are still read and merged into the `MiniMax H3` profile.

### `Global_Vibe` is now a real scene-level synthesis (bug fix)
- **Root cause**: the synthesis call reused the *image* preset (`global_image_mode`, default `Subject / Identity`) **and** the per-media JSON system prompt (`{"<Picture 1>": ...}`), so the model simply re-described the first reference.
- **Fix**: `Global_Vibe` now has its own presets (`global_vibe_prompts`), its own dropdown (`global_vibe_mode`), its own per-profile system prompt (`global_vibe_system_prompt`) and a text-only user prompt that explicitly forbids describing a single reference. It is emitted inside `vision_context` **and** on the dedicated `global_vibe` output.
- Force it from the node with one line: `Global_Vibe: one shared neon-noir world, wet asphalt, volumetric haze`.
- **Robust parsing**: fenced JSON, plain prose, `global_vibe` / `Global Vibe` key variants, and "the model answered with media keys" are all handled.

### Cross-Version Compatibility Fix
- `io.Autogrow` only exists on newer ComfyUI builds; on older ones the whole pack failed to import (`module 'comfy_api.latest._io' has no attribute 'Autogrow'`) and none of the three nodes appeared.
- New `py/io_compat.py` uses `io.Autogrow` when available and otherwise falls back to optional single-slot inputs (`image_1…9`, `video_1…3`, `audio_1…3`, and `image_1…9` text boxes on the Builder). Both the Analyzer and the Builder now load on old and new builds.
- `py/vision_profiles.py` keeps the instruction sets, with built-in defaults used when `vision_prompts.json` is missing or corrupt.

---

## Release Notes: v1.1.0

### Infinite Dynamic Sockets (ComfyAPI v3 Autogrow)
- **Limitless scaling**: Refactored the `H3_Vision_Analyzer` to completely utilize ComfyUI's native API v3 `Autogrow` inputs. The rigid 4-image limit is gone. Users can now infinitely chain as many `<Picture>` and `<Video>` references as their ComfyUI can handle without cluttering the screen with unused ports.

### Unprecedented Fine-Grained Prompt Overrides
- **Laser-focused Control**: Added a powerful multi-line text widget (`custom_prompt_override`) to the Vision Analyzer. By typing `<Picture 2>: focus entirely on lighting` or `image_3: describe the sword only`, users can surgically override the Vision LLM instructions for specific frames, while allowing all unmentioned media to intelligently fall back to the global analysis modes.

### Invisible VRAM Unloading & Management
- **Seamless Local Hosting**: Optimizing for 16GB VRAM set-ups, the explicit VRAM UI toggle has been replaced with invisible background logic. When selecting local providers like `ollama`, the node automatically wraps execution in `model_management.unload_all_models()` and `soft_empty_cache()`, preventing the user from ever seeing OOM errors when transitioning from LLM analysis to actual H3 video generation.

### Core Prompt Architecture Upgrade & De-Patching (The "Clean Blueprint" Update)
- **Zero-Hallucination Inline Tagging**: We entirely refactored the prompt compilation process. Previously, LLMs were forbidden from using `<Picture X>` tags, leading to severe tag parsing conflicts. Now, the internal pipeline explicitly calculates available visual anchors and seamlessly forces the LLM to embed these tags *directly into the narrative action lines*, perfectly mimicking Official Minimax H3 documentation.
- **Flawless 6-Part Output Integration**: The `H3_Promptor` no longer relies on complex regex fallbacks. It uses a pristine Python string-builder sequence to accurately stack the mandatory 6-part schema (`subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, `non_diegetic_music`) exactly as HuggingFace mandates.
- **Audio Routing Fix**: Patched a fatal loop gap where Audio-to-Video and Image-to-Audio pipelines were accidentally being ignored by the detector.
- **Sequential Multi-Modal Processing**: The Vision Analyzer now processes multiple images and videos sequentially (one at a time) rather than in a batch. This wholly prevents API request failures from downstream proxies limiting token structures, and eliminates VLM image-confusion during processing.

### "Auto" Intuitive Media Routing
- **Smart UX Dropdowns**: We abandoned the rigid `0` integer sliders for media counts. The UI now features intelligent Dropdown menus defaulting to `"Auto"`. When disconnected, it stays at 0 (perfect for Text-to-Video). The moment a Vision Analyzer is attached, "Auto" (or any manual number) is effortlessly overridden by the underlying engine for flawless multi-modal stability.

### Millisecond Timestamp Alignment
- **Automated Precision**: For multi-image setups (FL2VA) or time-sensitive inputs, the system now mathematically calculates precise cuts and first/last frame alignments based on your exact video duration.

### Dynamic Word Budget
- **Smarter Length Control**: The prompt builder now calculates an optimal word allowance depending on the target duration of your video. This actively prevents the LLM from over-describing short clips and ensures concise, highly-effective action descriptions.

### Strict Audio/Music Separation
- **Independent Sound Tracks**: All audio-related instructions are now forcefully extracted and formatted into their dedicated environment (Audio) and non-diegetic (Music) parameters, ensuring clean sound generation without mixed directives.

### Official Token Compatibility
- **Full Latent Binding Support**: Replaced legacy `Image1` style tags with the official `<Picture 1>` and `<Video 1>` tokens. This ensures flawless cross-attention injection and perfect compatibility across all ComfyUI MiniMax ecosystem nodes.

### Comprehensive Documentation
- **Official Master Tutorials**: Created `tutorials.md` and `tutorials_zh.md`, replacing heavy backend code documentation with 9 practical, production-ready Workflow Recipes (including Lip-Sync, Anime Style Transfer, Day-to-Night Morph, and more).
