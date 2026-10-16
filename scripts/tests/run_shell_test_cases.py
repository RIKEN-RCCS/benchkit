#!/usr/bin/env python3
"""Run independent shell test cases with two workers and ordered output."""
import concurrent.futures
from pathlib import Path
import subprocess
import sys
import time


def run_case(root, case):
    script, separator, part = case.partition("::")
    command = ["bash", str(root / script)] + ([part] if separator else [])
    started = time.monotonic()
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return case, result.returncode, result.stdout, time.monotonic() - started


def main(args):
    root = Path(args[0])
    cases = args[1:]
    if not cases or len(cases) != len(set(cases)):
        print("Shell test cases must be nonempty and unique", file=sys.stderr)
        return 2
    status = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for case, code, output, elapsed in pool.map(lambda case: run_case(root, case), cases):
            print("==> {} ({:.2f}s)".format(case, elapsed), flush=True)
            sys.stdout.buffer.write(output)
            sys.stdout.flush()
            if code and not status:
                status = code if code > 0 else 128 - code
    print("Ran {} shell test case(s) (jobs=2)".format(len(cases)))
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
