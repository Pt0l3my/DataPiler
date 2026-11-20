"""A stand-in for EldenNet's devkit tool in DataPiler's tests (S98): it plays `eldennet-engine.exe probe-exe` and
`lint`, with fixed outputs and exit codes that a test writes beside the fake tool, and records each call. It reads no
executable and writes nothing but the report a plan gives it. Run as `python -I devkit_standin.py <tool> <args>...`,
as the runner's `devkit_launch` starts it in the tests; every byte it writes is invented.

The plan, `stand-in-plan.json` in the fake tool's folder: {"probe-exe": step, "lint": step}, each step
{"code": n, "stdout": [lines], "stderr": [lines], "report": text written to --out (probe-exe), "sleep": seconds}."""

import json
import os
import sys
import time


def main(argv: list[str]) -> int:
    tool, args = argv[1], argv[2:]
    folder = os.path.dirname(tool)
    with open(os.path.join(folder, "stand-in-plan.json"), encoding="utf-8") as f:
        plan = json.load(f)
    with open(os.path.join(folder, "stand-in-calls.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd(), "stdin": sys.stdin is None or sys.stdin.read() == ""})
                + "\n")
    command = args[0] if args else ""
    step = plan.get(command)
    if step is None:
        sys.stderr.write("%s: usage\n" % (command or "eldennet-engine"))
        return 2
    if command == "probe-exe" and step.get("report") is not None:
        out = args[args.index("--out") + 1]
        with open(out + ".part", "w", encoding="ascii", newline="\n") as f:
            f.write(step["report"])
        os.replace(out + ".part", out)
    for line in step.get("stdout", []):
        sys.stdout.write(line + "\n")
    for line in step.get("stderr", []):
        sys.stderr.write(line + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    if step.get("sleep"):
        time.sleep(float(step["sleep"]))
    return int(step.get("code", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
