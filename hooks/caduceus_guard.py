#!/usr/bin/env python3
"""Standalone guard hook entry for Hermes pre_tool_call.

Use this file directly in hooks config if `cad` isn't on the PATH hermes uses:

hooks:
  pre_tool_call:
    - matcher: "terminal|code_execution"
      command: "python3 /Users/sashalabbe/projects/caduceus/hooks/caduceus_guard.py"
      timeout: 10
      fail_closed: true
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caduceus.guard import hook_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(hook_main())
