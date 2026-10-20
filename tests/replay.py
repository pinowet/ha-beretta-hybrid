"""Offline replay of a sniffer capture (frame.csv) through the decoder.

Usage:
    python tests/replay.py path/to/frame.csv [HH:MM:SS ...]

Rebuilds the raw byte stream from the captured frames, feeds it to the parser
in random-sized chunks (as a TCP gateway would) and prints the decoded values
at the requested times.
"""

from __future__ import annotations

import csv
import importlib.util
import random
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "beretta_hybrid"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"beretta_hybrid.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Load the pure modules without importing the HA package __init__
import types  # noqa: E402

pkg = types.ModuleType("beretta_hybrid")
pkg.__path__ = [str(ROOT)]
sys.modules["beretta_hybrid"] = pkg
protocol = _load("protocol")
decoding = _load("decoding")


def load_frames(path: str) -> list[tuple[float, bytes]]:
    frames = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            ts = datetime.strptime(row["ora"], "%Y-%m-%d %H:%M:%S.%f").timestamp()
            frames.append((ts, bytes.fromhex(row["hex"])))
    return frames


def replay(path: str, checkpoints: list[str], seed: int = 1):
    frames = load_frames(path)
    rng = random.Random(seed)
    parser = protocol.FrameParser()
    pending = sorted(checkpoints)
    results = {}
    expected_frames = len(frames)
    for ts, frame in frames:
        hhmmss = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        while pending and hhmmss >= pending[0]:
            results[pending.pop(0)] = decoding.decode_all(parser.state)
        data = frame
        while data:
            n = rng.randint(1, 40)
            parser.feed(data[:n], ts)
            data = data[n:]
    for cp in pending:
        results[cp] = decoding.decode_all(parser.state)
    return parser.state, expected_frames, results


if __name__ == "__main__":
    state, expected, results = replay(sys.argv[1], sys.argv[2:])
    print(
        f"frames {state.frames}/{expected}  discarded {state.bytes_discarded}  "
        f"unmatched {state.unmatched_responses}  exceptions {state.exceptions}"
    )
    for cp, values in results.items():
        print(f"\n=== {cp}")
        for key, value in values.items():
            print(f"  {key:34} {value}")
