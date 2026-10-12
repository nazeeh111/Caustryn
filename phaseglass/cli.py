# SPDX-License-Identifier: MIT
"""Simulation, blind solve, experiment design and portable exports."""

import argparse
import sys
from .io import encoded, read_json, write_new


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="phaseglass",
        description="Simulated radio observability. No hardware or pose claims.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    studio = commands.add_parser("studio", help="Open loopback experiment studio")
    studio.add_argument("--port", type=int, default=6365)
    for name in ("simulate", "solve", "intervention", "export"):
        command = commands.add_parser(name)
        command.add_argument(
            "input", help="Scene JSON for simulate; blind measurement JSON otherwise"
        )
        command.add_argument(
            "--output",
            help="New output file; existing files are never overwritten",
            required=name == "export",
        )
        if name == "intervention":
            command.add_argument(
                "--result",
                required=True,
                help="Result JSON from solving the same measurement",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "studio":
            if not 0 <= args.port <= 65535:
                raise ValueError("Port must lie within 0..65535")
            from .server import serve

            serve(args.port)
            return 0
        source = read_json(args.input)
        from .server import analyze

        payload = {"scene" if args.command == "simulate" else "measurement": source}
        if args.command == "intervention":
            payload["result"] = read_json(args.result)
        result = analyze(args.command, payload)
        if args.command == "export":
            import base64

            data = base64.b64decode(result["zip_base64"], validate=True)
        else:
            data = encoded(result) + b"\n"
        if args.output:
            write_new(args.output, data)
        else:
            sys.stdout.buffer.write(data)
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print("phaseglass: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
