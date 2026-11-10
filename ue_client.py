"""Tiny client for the Unreal Editor's MCP server (Epic's Unreal MCP plugin, http://127.0.0.1:8000/mcp).

The editor runs tool calls one at a time on its game thread, so every call here goes through one lock.
"""
import base64
import json
import re
import threading
import urllib.request

URL = "http://127.0.0.1:8000/mcp"
_H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_lock = threading.Lock()
_sid = None


class UEError(RuntimeError):
    pass


def _rpc(method, params, sid=None, rid=1, timeout=900):
    h = dict(_H)
    if sid:
        h["Mcp-Session-Id"] = sid
    body = {"jsonrpc": "2.0", "method": method, "params": params}
    if rid is not None:
        body["id"] = rid
    req = urllib.request.Request(URL, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        sid = r.headers.get("Mcp-Session-Id") or sid
        txt = r.read().decode("utf-8", "replace")
    if txt.startswith(("event:", "data:")):
        txt = "\n".join(l[5:] for l in txt.splitlines() if l.startswith("data:"))
    return (json.loads(txt) if txt.strip() else {}), sid


def _session():
    global _sid
    if _sid is None:
        _, sid = _rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "ue-kit", "version": "1"}})
        _rpc("notifications/initialized", {}, sid, rid=None)
        _sid = sid
    return _sid


def _text(res):
    if "error" in res:
        raise UEError(json.dumps(res["error"], ensure_ascii=False)[:800])
    out = [c.get("text", "") for c in res.get("result", {}).get("content", [])]
    return "\n".join(out)


def call(toolset, tool, args):
    """Calls one editor tool; returns the parsed JSON result (usually {"returnValue": ...})."""
    global _sid
    with _lock:
        for attempt in (1, 2):
            try:
                res, _ = _rpc("tools/call", {"name": "call_tool", "arguments": {
                    "toolset_name": toolset, "tool_name": tool, "arguments": args}}, _session(), rid=2)
                break
            except OSError:
                if attempt == 2:
                    raise UEError("Unreal Editor MCP server not reachable at " + URL +
                                  " - is the editor open with the Unreal MCP server running?")
                _sid = None
    txt = _text(res)
    try:
        return json.loads(txt)
    except ValueError:
        raise UEError(txt[:800])


def batch(script, data=None):
    """Runs a sandboxed tool script inside the editor (ProgrammaticToolset.execute_tool_script).
    The script defines run() and may use DATA (any JSON value) and execute_tool(name, json_str)."""
    if data is not None:
        script = "import json\nDATA = json.loads(" + repr(json.dumps(data)) + ")\n" + script
    r = call("editor_toolset.toolsets.programmatic.ProgrammaticToolset", "execute_tool_script", {"script": script})
    v = r.get("returnValue", r)
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            raise UEError(v[:800])
    return v


def save_png(result, path):
    """Finds the first base64 PNG in a tool result and writes it to path."""
    m = re.search(r'"data"\s*:\s*"([A-Za-z0-9+/=]{100,})"', json.dumps(result))
    if not m:
        raise UEError("no image in result: " + json.dumps(result)[:300])
    with open(path, "wb") as f:
        f.write(base64.b64decode(m.group(1)))
    return path
