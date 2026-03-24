"""Filter FRIDAY responses for voice output.

Strips code, markdown, URLs — keeps it conversational.
"""

import re
from friday.voice.config import MAX_VOICE_SENTENCES


def filter_for_voice(text: str) -> tuple[str, str]:
    """Filter response into (voice_text, display_text).

    voice_text: what gets spoken aloud (clean, short)
    display_text: full original for terminal display

    Returns:
        Tuple of (voice_text, display_text).
    """
    display_text = text

    # Check if response is mostly code
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    text_without_code = re.sub(r"```[\s\S]*?```", "", text).strip()

    if code_blocks and len(text_without_code) < 30:
        return "Done. Check the screen.", display_text

    # Strip code blocks
    voice = re.sub(r"```[\s\S]*?```", "", text)

    # Strip inline code
    voice = re.sub(r"`[^`]+`", "", voice)

    # Strip markdown headers
    voice = re.sub(r"^#{1,6}\s+", "", voice, flags=re.MULTILINE)

    # Strip bold/italic
    voice = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", voice)

    # Strip bullet points and numbered lists
    voice = re.sub(r"^\s*[-•→]\s*", "", voice, flags=re.MULTILINE)
    voice = re.sub(r"^\s*\d+\.\s*", "", voice, flags=re.MULTILINE)

    # Strip URLs
    voice = re.sub(r"https?://\S+", "", voice)

    # Strip file paths
    voice = re.sub(r"(?:/[\w.-]+){2,}", "", voice)

    # Collapse whitespace
    voice = re.sub(r"\n{2,}", ". ", voice)
    voice = re.sub(r"\n", " ", voice)
    voice = re.sub(r"\s{2,}", " ", voice)
    voice = voice.strip()

    if not voice:
        return "Done. Check the screen.", display_text

    # Condense to MAX_VOICE_SENTENCES
    sentences = re.split(r"(?<=[.!?])\s+", voice)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) > MAX_VOICE_SENTENCES:
        voice = " ".join(sentences[:MAX_VOICE_SENTENCES])
        if not voice.endswith((".", "!", "?")):
            voice += "."

    return voice, display_text
