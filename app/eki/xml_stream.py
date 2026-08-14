from __future__ import annotations

from typing import Optional


def extract_first_complete_xml(text: str) -> tuple[Optional[str], str]:
    """Return the first complete XML document and the remaining buffer."""
    if not text:
        return None, text

    start = text.find("<")
    if start == -1:
        return None, ""

    if start > 0:
        text = text[start:]

    gt = text.find(">")
    if gt == -1:
        return None, text

    open_tag = text[1:gt].strip()
    if not open_tag or open_tag.startswith("?") or open_tag.startswith("!"):
        next_lt = text.find("<", gt + 1)
        if next_lt == -1:
            return None, text
        return extract_first_complete_xml(text[next_lt:])

    root_name = open_tag.split()[0]
    closing_tag = f"</{root_name}>"
    end_idx = text.find(closing_tag)
    if end_idx == -1:
        return None, text

    end_idx += len(closing_tag)
    return text[:end_idx], text[end_idx:]


def drain_xml_packets(buffer: str, handler) -> str:
    """Repeatedly extract XML packets from buffer and pass each to handler."""
    while True:
        packet, buffer = extract_first_complete_xml(buffer)
        if packet is None:
            return buffer
        handler(packet)
