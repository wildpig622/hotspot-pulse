#!/usr/bin/env python3
"""Validate a manual workflow request without collecting, writing or deploying."""
from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping

CONFIRMATIONS = {"collect": "COLLECT_PENDING_ONLY", "deploy": "DEPLOY_REVIEWED_SITE"}
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def request_errors(action: str, environ: Mapping[str, str]) -> list[str]:
    if action not in CONFIRMATIONS:
        return ["unknown_action"]
    errors = []
    if environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        errors.append("manual_dispatch_required")
    if environ.get("GITHUB_REF") != "refs/heads/main":
        errors.append("main_branch_required")
    actual = environ.get("GITHUB_SHA", "")
    expected = environ.get("REQUESTED_SHA", "")
    if not FULL_SHA.fullmatch(actual):
        errors.append("invalid_workflow_sha")
    if not FULL_SHA.fullmatch(expected):
        errors.append("full_expected_sha_required")
    elif actual != expected:
        errors.append("commit_mismatch")
    if environ.get("REQUEST_CONFIRMATION") != CONFIRMATIONS[action]:
        errors.append("explicit_action_confirmation_required")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(CONFIRMATIONS))
    action = parser.parse_args(argv).action
    errors = request_errors(action, os.environ)
    if errors:
        print(json.dumps({"status": "DENIED", "action": action, "reasons": errors}))
        return 1
    print(json.dumps({"status": "REQUEST_VALIDATED", "action": action, "sha": os.environ["GITHUB_SHA"],
                      "execution_performed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
