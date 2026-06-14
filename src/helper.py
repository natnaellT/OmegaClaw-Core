from collections import deque
import json
import re
from datetime import datetime

TS_RE = re.compile(r'^\("(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"')
LLM_COMMANDS = {
    "append-file",
    "episodes",
    "metta",
    "pin",
    "query",
    "read-file",
    "remember",
    "search",
    "send",
    "shell",
    "tavily-search",
    "technical-analysis",
    "write-file",
    "bio-index",
    "bio-reindex",
    "bio-query",
    "bio-extract",
    "bio-path",
    "bio-pln-evidence-merge",
    "bio-pln-chain-confidence"
}

_WRAPPER_PATTERNS = [
    (re.compile(r"\[TOOL_CALL\]\s*", re.IGNORECASE), ""),
    (re.compile(r"\s*\[/TOOL_CALL\]", re.IGNORECASE), ""),
    (re.compile(r"<tool_call>\s*", re.IGNORECASE), ""),
    (re.compile(r"\s*</tool_call>", re.IGNORECASE), ""),
    (re.compile(r"<function_call>\s*", re.IGNORECASE), ""),
    (re.compile(r"\s*</function_call>", re.IGNORECASE), ""),
    (re.compile(r"^```[a-zA-Z0-9_]*\s*$", re.MULTILINE), ""),
    (re.compile(r"^```\s*$", re.MULTILINE), ""),
]

_DROP_LINE_PATTERNS = [
    re.compile(r"^\s*\{\s*\}\s*$"),
    re.compile(r"^\s*\[\s*\]\s*$"),
    re.compile(r"^\s*\(\s*\)\s*$"),
    re.compile(r"^\s*\(?\s*empty\s*\)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(?\s*none\s*\)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(?\s*null\s*\)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\{\s*\"name\"\s*:\s*\".*?\"\s*,?\s*"),
]

_MONOLOGUE_STARTS = (
    "i should ", "i need to ", "i will ", "let me ", "looking at ",
    "based on the ", "according to ", "the user is asking", "now i need to",
    "acknowledged.", "understood.", "noted.", "got it."
)


def extract_timestamp(line):
    m = TS_RE.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def around_time(needle_time_str, k):
    needle_time_str = needle_time_str.replace(r'\"', '').replace('"', '').strip()
    filename = "repos/OmegaClaw-Core/memory/history.metta"
    target = datetime.strptime(needle_time_str, "%Y-%m-%d %H:%M:%S")
    best_lineno = None
    best_diff = None
    buffer = []
    best_idx = None
    with open(filename, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            buffer.append((lineno, line))
            ts = extract_timestamp(line)
            if ts is None:
                continue
            diff = abs((ts - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_lineno = lineno
                best_idx = len(buffer) - 1
    if best_lineno is None:
        return
    start = max(0, best_idx - k)
    end = min(len(buffer), best_idx + k + 1)
    ret = ""
    for lineno, line in buffer[start:end]:
        ret += f"{lineno}:{line}"
    return ret


def _strip_outer_parens(line):
    if line.startswith("(") and line.endswith(")"):
        return line[1:-1].strip()
    return line


def _get_command_name(line):
    normalized = line.strip()
    while normalized.startswith("("):
        normalized = normalized[1:].lstrip()
    while normalized.endswith(")"):
        normalized = normalized[:-1].rstrip()
    if not normalized:
        return ""
    return normalized.split(maxsplit=1)[0]


def _is_known_command(line):
    return _get_command_name(line) in LLM_COMMANDS


def _decode_quoted_arg(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def _merge_send_continuations(lines):
    merged = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if _get_command_name(line) != "send":
            merged.append(line)
            idx += 1
            continue

        send_wrapped = line.strip().startswith("(")
        head = line.strip()
        while head.startswith("("):
            head = head[1:].lstrip()
        parts = head.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        decoded_payload = _decode_quoted_arg(payload) if payload.startswith('"') else None
        text = decoded_payload if decoded_payload is not None else payload

        idx += 1
        continuations = []
        while idx < len(lines) and not _is_known_command(lines[idx]):
            continuation = lines[idx].strip()
            if send_wrapped and continuation.endswith(")"):
                continuation = continuation[:-1].rstrip()
                continuations.append(continuation)
                idx += 1
                break
            continuations.append(continuation)
            idx += 1

        if continuations:
            if text:
                text = text + "\n" + "\n".join(continuations)
            else:
                text = "\n".join(continuations)
            merged.append(f"send {json.dumps(text, ensure_ascii=False)}")
        else:
            merged.append(line)
    return merged


def sanitize_llm_response(raw: str) -> str:
    """Strip wrapper bleed and auto-wrap orphan prose."""
    if not isinstance(raw, str):
        return raw

    text = raw.replace("_quote_", '"').replace("_newline_", "\n")

    for pat, repl in _WRAPPER_PATTERNS:
        text = pat.sub(repl, text)

    send_count = 0
    out_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if any(p.match(line) for p in _DROP_LINE_PATTERNS):
            continue

        inner = line
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1].strip()
        if not inner:
            continue
            
        parts = inner.split(maxsplit=1)
        first = parts[0] if parts else ""
        first = first.strip('"').strip("'")

        if _is_known_command(first) or first.startswith("bio-"):
            if first == "send":
                body = parts[1].strip() if len(parts) > 1 else ""
                body_inspect = body.strip('"').strip("'").strip().lower()
                if any(body_inspect.startswith(p) for p in _MONOLOGUE_STARTS):
                    continue
                if send_count >= 1:
                    continue
                send_count += 1
            out_lines.append(raw_line)
        else:
            cleaned = inner.lstrip("-*").strip()
            if not cleaned:
                continue
            if any(cleaned.lower().startswith(p) for p in _MONOLOGUE_STARTS):
                continue
            if send_count >= 1:
                continue
            send_count += 1
            out_lines.append(f"send {cleaned}")

    return "\n".join(out_lines)


def balance_parentheses(s):
    s = sanitize_llm_response(s)
    s = s.replace("_quote_", '"').replace("_newline_", "\n")
    sexprs = []
    special_two_arg_cmds = {"write-file", "append-file"}
    lines = [line.strip() for line in s.splitlines() if line.strip()]
    lines = _merge_send_continuations(lines)
    for line in lines:
        if line.startswith("(-"):
            line = "(pin -" + line[2:]
        elif line.startswith("-"):
            line = "pin " + line
            
        line = _strip_outer_parens(line)
        parts = line.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        
        if cmd in special_two_arg_cmds:
            if not rest:
                sexprs.append(f"({cmd})")
                continue
            if rest.startswith('"'):
                end = 1
                escaped = False
                while end < len(rest):
                    ch = rest[end]
                    if ch == '"' and not escaped:
                        break
                    escaped = (ch == '\\' and not escaped)
                    if ch != '\\':
                        escaped = False
                    end += 1
                if end < len(rest) and rest[end] == '"':
                    filename = rest[:end+1]
                    content = rest[end+1:].strip()
                else:
                    filename = '"' + rest[1:].replace('"', '\\"') + '"'
                    content = ""
            else:
                split_rest = rest.split(maxsplit=1)
                filename = '"' + split_rest[0].replace('"', '\\"') + '"'
                content = split_rest[1].strip() if len(split_rest) > 1 else ""
                
            if content:
                if content.startswith('"') and content.endswith('"'):
                    sexprs.append(f"({cmd} {filename} {content})")
                else:
                    content = content.replace('"', '\\"')
                    sexprs.append(f'({cmd} {filename} "{content}")')
            else:
                sexprs.append(f"({cmd} {filename})")
            continue
            
        if rest:
            if rest.startswith('"') and rest.endswith('"'):
                sexprs.append(f"({cmd} {rest})")
            else:
                rest = rest.replace('"', '\\"')
                sexprs.append(f'({cmd} "{rest}")')
        else:
            sexprs.append(f"({cmd})")
            
    ret = " ".join(sexprs)
    return "(" + ret + ")"


def normalize_string(x):
    try:
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="ignore")
        return str(x).encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return str(x)
