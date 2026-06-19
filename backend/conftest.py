from __future__ import annotations

import os


os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("TOOL_MODE", "mock")
