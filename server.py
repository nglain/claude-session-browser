#!/usr/bin/env python3
"""Claude Code Session Browser - Web UI for browsing and resuming sessions."""

import json
import os
import re
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
TITLES_DIR = CLAUDE_DIR / ".statusline-titles"
CURRENT_SESSION_FILE = CLAUDE_DIR / ".current-session"

PORT = 7654


def get_custom_titles():
    titles = {}
    if TITLES_DIR.exists():
        for f in TITLES_DIR.iterdir():
            if f.is_file():
                try:
                    titles[f.name] = f.read_text().strip()
                except Exception:
                    pass
    return titles


def get_current_session():
    try:
        return CURRENT_SESSION_FILE.read_text().strip()
    except Exception:
        return None


def parse_jsonl_session(jsonl_path, extract_messages=3):
    """Parse a JSONL session file to extract metadata and last user messages."""
    session_id = None
    project_path = None
    git_branch = None
    version = None
    first_user_text = None
    user_messages = []
    message_count = 0
    first_ts = None
    last_ts = None

    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue

                # Track timestamps
                ts = d.get("timestamp")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                # Extract session metadata from any message
                if not session_id and d.get("sessionId"):
                    session_id = d["sessionId"]
                if not project_path and d.get("cwd"):
                    project_path = d["cwd"]
                if not git_branch and d.get("gitBranch"):
                    git_branch = d["gitBranch"]
                if not version and d.get("version"):
                    version = d["version"]

                if d.get("type") == "user":
                    message_count += 1
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text += c.get("text", "")

                    stripped = text.strip()
                    if (
                        not stripped
                        or stripped.startswith("<task-notification")
                        or stripped.startswith("<system")
                    ):
                        continue

                    clean = stripped[:200].replace("\n", " ").replace("\r", "")
                    if first_user_text is None:
                        first_user_text = clean
                    user_messages.append(clean)

                elif d.get("type") == "assistant":
                    message_count += 1

    except Exception:
        pass

    if not session_id:
        # Derive from filename
        session_id = Path(jsonl_path).stem

    return {
        "sessionId": session_id,
        "projectPath": project_path or "",
        "gitBranch": git_branch or "",
        "firstPrompt": first_user_text or "",
        "messageCount": message_count,
        "created": first_ts or "",
        "modified": last_ts or "",
        "lastMessages": user_messages[-extract_messages:] if user_messages else [],
        "version": version or "",
    }


def get_all_sessions():
    sessions = []
    titles = get_custom_titles()
    current = get_current_session()
    seen_ids = set()

    if not PROJECTS_DIR.exists():
        return sessions

    # First pass: collect from sessions-index.json (fast, has summary)
    indexed = {}
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        index_file = project_dir / "sessions-index.json"
        if not index_file.exists():
            continue
        try:
            data = json.loads(index_file.read_text())
            for entry in data.get("entries", []):
                sid = entry.get("sessionId", "")
                if sid:
                    indexed[sid] = entry
        except Exception:
            pass

    # Second pass: scan all JSONL files (catches unindexed sessions)
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            sid = jsonl_file.stem
            if sid in seen_ids:
                continue
            seen_ids.add(sid)

            # Use index data if available, supplement with JSONL parsing
            idx = indexed.get(sid, {})

            # Always parse JSONL for messages and accurate timestamps
            parsed = parse_jsonl_session(str(jsonl_file), extract_messages=3)

            entry = {
                "sessionId": sid,
                "fullPath": str(jsonl_file),
                "summary": idx.get("summary", ""),
                "firstPrompt": parsed["firstPrompt"] or idx.get("firstPrompt", ""),
                "messageCount": parsed["messageCount"] or idx.get("messageCount", 0),
                "created": parsed["created"] or idx.get("created", ""),
                "modified": parsed["modified"] or idx.get("modified", ""),
                "projectPath": parsed["projectPath"] or idx.get("projectPath", ""),
                "gitBranch": parsed["gitBranch"] or idx.get("gitBranch", ""),
                "isSidechain": idx.get("isSidechain", False),
                "lastMessages": parsed["lastMessages"],
                "customTitle": titles.get(sid, ""),
                "isCurrent": sid == current,
            }

            # Use file mtime as fallback for modified
            if not entry["modified"]:
                try:
                    mtime = jsonl_file.stat().st_mtime
                    entry["modified"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            sessions.append(entry)

    # Filter out empty sessions and sort by modified date descending
    sessions = [s for s in sessions if s.get("messageCount", 0) > 0]
    sessions.sort(key=lambda s: s.get("modified", ""), reverse=True)
    return sessions


def open_terminal_with_resume(session_id, project_path=""):
    """Open Terminal.app with cl --resume in the session's project directory."""
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', session_id):
        return False, "Invalid session ID"

    parts = []
    if project_path and os.path.isdir(project_path):
        parts.append(f"cd {project_path}")
    parts.append(f"cl --resume {session_id}")
    cmd = " && ".join(parts)

    script = (
        'tell application "Terminal"\n'
        "  activate\n"
        f'  do script "{cmd}"\n'
        "end tell"
    )
    try:
        subprocess.run(["osascript"], input=script, text=True, check=True, timeout=5)
        return True, "OK"
    except Exception as e:
        return False, str(e)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/sessions":
            sessions = get_all_sessions()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(sessions).encode())
            return

        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html_path = Path(__file__).parent / "index.html"
            self.wfile.write(html_path.read_bytes())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/resume":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            sid = body.get("sessionId", "")
            project = body.get("projectPath", "")

            ok, msg = open_terminal_with_resume(sid, project)

            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": ok, "message": msg}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Session Browser running at {url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
