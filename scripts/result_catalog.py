#!/usr/bin/env python3
"""Explicit, local rebuild of a derived Result candidate catalog."""

import argparse
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "result_server"))
from utils.result_catalog import CatalogUnavailable, ResultCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument('--estimates', help='Estimate directory, including an empty directory')
    parser.add_argument('--artifacts', help='Measurement archive directory, including an empty directory')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--initialize", action="store_true", help="Create a NEW catalog before rebuilding")
    modes.add_argument('--upgrade', action='store_true', help='Upgrade a version 1 derived catalog before rebuilding')
    args = parser.parse_args()
    try:
        catalog = ResultCatalog(args.catalog, args.results, estimated_directory=args.estimates,
                                artifact_directory=args.artifacts)
        if args.initialize:
            catalog.initialize()
        if args.upgrade:
            catalog.upgrade()
        catalog.rebuild()
    except (CatalogUnavailable, sqlite3.Error, OSError, ValueError):
        parser.exit(1, "Catalog rebuild failed; candidates are unavailable. Source Results were not modified.\n")
    print("Catalog rebuild completed. Source Results were not modified.")


if __name__ == "__main__":
    main()
