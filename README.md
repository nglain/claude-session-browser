# Claude Session Browser

Web UI for browsing Claude Code sessions and quickly getting `session_id` for the `claude --resume` command.

![Python](https://img.shields.io/badge/python-3.8+-blue) ![No Dependencies](https://img.shields.io/badge/dependencies-none-green)

## Features

- Discovers all sessions by scanning `~/.claude/projects/**/*.jsonl` files directly
- Shows last 2-3 user messages per session for quick context
- Search across titles, prompts, messages, session IDs, projects, branches
- Filter by: All / Titled / Last 24h
- Project dropdown filter with session counts
- Date grouping: Today, Yesterday, This Week, This Month, Older
- One-click copy of session ID or full `claude --resume <id>` command
- Highlights active session and custom titles (set via `/title`)
- Auto-refresh every 30 seconds
- Zero dependencies — pure Python + vanilla JS

## Usage

```bash
python3 server.py
```

Opens `http://127.0.0.1:7654` in your browser.

## Install

```bash
git clone https://github.com/nglain/claude-session-browser.git
cd claude-session-browser
python3 server.py
```

## How it works

1. Scans all `~/.claude/projects/*/` directories for `.jsonl` session files
2. Parses each file to extract: session ID, timestamps, user messages, project path, git branch
3. Merges with `sessions-index.json` data (for summaries) and `~/.statusline-titles/` (for custom titles)
4. Serves a single-page app on localhost with a JSON API

## Data sources

| Source | What it provides |
|--------|-----------------|
| `~/.claude/projects/*/*.jsonl` | Session transcripts, timestamps, messages |
| `~/.claude/projects/*/sessions-index.json` | AI-generated summaries |
| `~/.claude/.statusline-titles/` | Custom session titles (from `/title`) |
| `~/.claude/.current-session` | Currently active session ID |
