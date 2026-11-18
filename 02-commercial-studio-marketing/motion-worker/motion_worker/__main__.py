"""``python -m motion_worker``: start the worker (configuration comes from the environment)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence

from . import __version__
from .config import Config
from .errors import ConfigError
from .logs import configure_logging, event
from .pipeline import build_pipeline
from .transport import build_transport
from .worker import Worker, install_signal_handlers


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m motion_worker", description="Spotlight GPU motion worker")
    parser.add_argument("--print-config", action="store_true", help="print the resolved configuration and exit")
    parser.add_argument("--version", action="version", version=f"motion-worker {__version__}")
    args = parser.parse_args(argv)
    try:
        cfg = Config.from_env(env)
    except ConfigError as exc:
        print(f"motion-worker: {exc}", file=sys.stderr)
        return 2
    configure_logging(cfg.log_level)
    if args.print_config:
        print(json.dumps(cfg.public_dict(), indent=2, sort_keys=True))
        return 0
    try:
        worker = Worker(cfg, build_transport(cfg), build_pipeline(cfg))
    except Exception as exc:  # noqa: BLE001 - e.g. Azure SDK missing; report once, clearly, as JSON
        event("worker_init_failed", level=40, error=f"{type(exc).__name__}: {exc}")
        return 3
    install_signal_handlers(worker)
    return worker.run()


if __name__ == "__main__":
    raise SystemExit(main())
