"""Server-Sent Events framing: `event: <type>` + one line of JSON + a blank line."""

import json

from lineup_lab.agent.events import Event, to_payload


def format_event(event: Event) -> bytes:
    data = json.dumps(to_payload(event), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.type}\ndata: {data}\n\n".encode()
