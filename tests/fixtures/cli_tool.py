"""Stand in for sha256sum and fastboot when testing the shell runbook."""

import json
import os
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
log = Path(os.environ["MX5_TEST_LOG"])
record = {"tool": tool, "args": sys.argv[1:]}
if tool == "sha256sum":
    record["input"] = sys.stdin.read()
with log.open("a") as output:
    output.write(json.dumps(record) + "\n")
if tool == "sha256sum":
    sys.exit(int(os.environ.get("MX5_TEST_CHECKSUM_STATUS", "0")))
if sys.argv[1:] == ["devices"]:
    print(os.environ.get("MX5_TEST_DEVICES", "MX5TEST\t Android Fastboot\n"), end="")
    sys.exit(int(os.environ.get("MX5_TEST_DEVICES_STATUS", "0")))
calls = [
    json.loads(line) for line in log.read_text().splitlines()
    if json.loads(line)["tool"] == "fastboot" and json.loads(line)["args"] != ["devices"]
]
sys.exit(1 if len(calls) == int(os.environ.get("MX5_TEST_FAIL_AT", "0")) else 0)
