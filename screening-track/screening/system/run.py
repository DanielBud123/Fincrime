#!/usr/bin/env python3
"""Entry point: system/run <data folder> <output file>

Reads only the data folder and writes one JSON line per hit. Standard library
only. Works as ``system/run dev output/dev.jsonl`` on Linux/macOS and as
``python system/run dev output/dev.jsonl`` anywhere.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from pipeline import run  # noqa: E402


def main(argv):
    if len(argv) != 2:
        print("usage: system/run <data folder> <output file>", file=sys.stderr)
        return 2
    run(argv[0], argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
