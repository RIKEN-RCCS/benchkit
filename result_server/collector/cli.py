"""Explicit one-shot Collector CLI; no deployment or automatic initialization."""

import argparse

from .collection import collect_batch
from .config import load_configuration
from .delivery import run_once
from .errors import DeliveryError
from .state import DeliveryState
from .transport import HTTPSDelivery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "collect"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        config = load_configuration(args.config)
        if args.command == "init":
            DeliveryState(config.state_directory, config.policy, config.endpoint).initialize()
            print("Collector state initialized")
        else:
            sender = HTTPSDelivery(config.endpoint, config.key_file)
            result = run_once(config.state_directory, config.policy, sender,
                              lambda seq: collect_batch(config.policy, config.targets, seq))
            print("Collector delivery: " + result)
        return 0
    except DeliveryError as error:
        print("Collector operation failed: " + error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
