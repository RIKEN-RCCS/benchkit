"""Durable, coalesced notifications between ingest and the publication worker."""
import fcntl
import os
from pathlib import Path


def notify_publication():
    directory = os.environ.get("RESULT_SERVER_PUBLICATION_QUEUE")
    if directory:
        Path(directory, "pending").touch(mode=0o600)


def publish_pending(directory, publisher):
    """Run from a path-activated or periodic trusted worker. Retry incomplete work."""
    directory = Path(directory)
    pending = directory / "pending"
    active = directory / "publishing"
    with (directory / "worker.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "busy"
        try:
            pending.replace(active)
        except FileNotFoundError:
            if not active.exists():
                return "idle"
        result = publisher.update()
        if result["status"] == "published":
            active.unlink()
        return result["status"]


def main():
    """One-shot worker for a service watching both pending and publishing markers."""
    import argparse
    import json
    from utils.cx_persistence import CxPersistence
    from utils.public_delivery import Publisher
    from utils.public_disclosure import AutomaticDisclosure
    from utils.public_supervisor import SystemdPublicationControl

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('configuration', type=Path)
    args = parser.parse_args()
    config = json.loads(args.configuration.read_text())
    store = CxPersistence(**config['store'])
    control = SystemdPublicationControl(**config['supervisor'])
    publisher = Publisher(store, control.root, control.private_state, control.reader_uid,
                          control=control, policy=AutomaticDisclosure(config['benchmarks']))
    publish_pending(config['queue'], publisher)


if __name__ == '__main__':
    main()
