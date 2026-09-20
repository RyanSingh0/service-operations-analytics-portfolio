import argparse
import json
from pathlib import Path

from serviceops.pipeline import download_source, run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Build incident analytics from a historical extract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--destination", default="data/raw/incident_event_log.csv")
    run = subparsers.add_parser("run")
    run.add_argument("--source", default="data/raw/incident_event_log.csv")
    run.add_argument("--output", default="build/local")
    run.add_argument("--as-of", help="Source-local timestamp, for example 2016-05-01 23:59:59")
    run.add_argument("--max-reject-rate", type=float, default=.01)
    args = parser.parse_args()
    if args.command == "download":
        print(download_source(args.destination))
    elif args.command == "run":
        template = Path("dashboard/index.html")
        result = run_pipeline(args.source, args.output, args.as_of, args.max_reject_rate, template)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
