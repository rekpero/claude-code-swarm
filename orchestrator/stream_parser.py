"""Parse Claude CLI stream-json output into structured events."""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    event_type: str  # "assistant", "tool_use", "tool_result", "result", "error", "system"
    summary: str     # human-readable one-liner for the dashboard
    raw: dict        # full parsed JSON


def parse_stream_line(line: str) -> AgentEvent | None:
    """Parse a single line of stream-json output from `claude -p --output-format stream-json`.

    Claude stream-json emits one JSON object per line. Key message types:
    - {"type": "assistant", "message": {...}}  — assistant text chunks
    - {"type": "tool_use", "tool": "...", ...} — tool invocations
    - {"type": "tool_result", ...}             — tool results
    - {"type": "result", ...}                  — final result
    - {"type": "system", ...}                  — system messages
    """
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.debug("Non-JSON line from stream: %s", line[:200])
        return None

    msg_type = data.get("type", "unknown")

    if msg_type == "assistant":
        # Extract text content from the message
        message = data.get("message", {})
        content_blocks = message.get("content", [])
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        text = " ".join(text_parts)[:200]
        return AgentEvent(event_type="assistant", summary=text or "(thinking...)", raw=data)

    elif msg_type == "tool_use":
        tool_name = data.get("tool", data.get("name", "unknown"))
        tool_input = data.get("input", {})
        # Build a useful summary
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")[:100]
            summary = f"Bash: {cmd}"
        elif tool_name == "Read":
            summary = f"Read: {tool_input.get('file_path', '?')}"
        elif tool_name in ("Edit", "Write"):
            summary = f"{tool_name}: {tool_input.get('file_path', '?')}"
        else:
            summary = f"{tool_name}: {json.dumps(tool_input)[:100]}"
        return AgentEvent(event_type="tool_use", summary=summary, raw=data)

    elif msg_type == "tool_result":
        return AgentEvent(event_type="tool_result", summary="(tool result)", raw=data)

    elif msg_type == "result":
        result_text = ""
        result_data = data.get("result", "")
        if isinstance(result_data, str):
            result_text = result_data[:200]
        elif isinstance(result_data, dict):
            result_text = json.dumps(result_data)[:200]
        return AgentEvent(event_type="result", summary=result_text or "Agent finished", raw=data)

    elif msg_type == "error":
        error_msg = data.get("error", {})
        if isinstance(error_msg, dict):
            error_msg = error_msg.get("message", str(error_msg))
        return AgentEvent(event_type="error", summary=str(error_msg)[:200], raw=data)

    else:
        return AgentEvent(event_type=msg_type, summary=json.dumps(data)[:200], raw=data)


def count_turns(events: list[AgentEvent]) -> int:
    """Count the number of assistant turns from a list of events."""
    return sum(1 for e in events if e.event_type == "assistant")


def extract_pr_number(events: list[AgentEvent]) -> int | None:
    """Try to extract a PR number from agent events (looking for gh pr create output)."""
    import re
    for event in reversed(events):
        raw_str = json.dumps(event.raw)
        # Look for patterns like "pull/123" or "PR #123" in the output
        matches = re.findall(r'(?:pull/|PR #|pr #|pull request #?)(\d+)', raw_str)
        if matches:
            return int(matches[-1])
    return None


def extract_session_id(events: list[AgentEvent]) -> str | None:
    """Try to extract a Claude session ID from agent events.

    Claude CLI stream-json may include session_id in system or result events.
    """
    for event in events:
        raw = event.raw
        # Check top-level fields
        sid = raw.get("session_id") or raw.get("sessionId")
        if sid:
            return str(sid)
        # Check nested in message or result
        for key in ("message", "result", "metadata"):
            nested = raw.get(key, {})
            if isinstance(nested, dict):
                sid = nested.get("session_id") or nested.get("sessionId")
                if sid:
                    return str(sid)
    return None
