"""Replay recorded sessions through the agent for integration testing."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .agent import Agent, TurnResult
from .session import SessionStore


def sessions_dir() -> Path:
    return Path(os.environ.get("MARDIK_SESSIONS_DIR", "sessions"))


def load_session(name: str) -> dict[str, Any]:
    path = sessions_dir() / f"{name}.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def replay(session_data: dict[str, Any], agent: Agent, store: SessionStore) -> TurnResult:
    """Replay a recorded session and return the result of its final turn."""
    session_id = session_data["session_id"]
    messages = session_data["messages"]
    # Replay the prior context so the final turn sees the whole conversation.
    for message in messages[:-1]:
        store.append(session_id, message)
    last = messages[-1]
    return agent.run_turn(store, session_id, last["content"])
