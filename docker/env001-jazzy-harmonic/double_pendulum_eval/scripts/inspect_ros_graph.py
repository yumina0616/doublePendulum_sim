#!/usr/bin/env python3
"""Phase 5 (Tool Architecture): ROS graph inspection tool.

Structured (JSON) snapshot of the live ROS graph -- nodes, topics, and each
topic's publisher/subscriber counts and type -- instead of manually reading
`ros2 node list` / `ros2 topic list` / `ros2 topic info` output by eye.

    python3 inspect_ros_graph.py
    python3 inspect_ros_graph.py --pretty
"""
import argparse
import json
import re
import subprocess


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout


def list_nodes():
    out = run(["ros2", "node", "list"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def list_topics():
    out = run(["ros2", "topic", "list"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def topic_info(name):
    out = run(["ros2", "topic", "info", "-v", name])
    msg_type = None
    pubs, subs = 0, 0
    section = None
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"Type:\s*(.+)", line)
        if m and msg_type is None:
            msg_type = m.group(1)
        if line.startswith("Publisher count:"):
            pubs = int(line.split(":")[1].strip())
        if line.startswith("Subscription count:"):
            subs = int(line.split(":")[1].strip())
    return {"type": msg_type, "publishers": pubs, "subscribers": subs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    nodes = list_nodes()
    topics = {name: topic_info(name) for name in list_topics()}

    result = {"nodes": nodes, "topics": topics}
    print(json.dumps(result, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
