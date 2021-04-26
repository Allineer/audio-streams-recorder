#!/usr/bin/env python3

"""
audio-streams-recorder v.{version}
==================================================

Usage:
    audio-streams-recorder daemon
    audio-streams-recorder --help
    audio-streams-recorder --version

Commands:
    daemon        run in daemon mode

Options:
    -h --help     show this help message and exit
    -v --version  show version and exit
"""

import asyncio
import logging
import sys
from signal import SIGINT, SIGTERM
from typing import Dict, List

import helpers.logging as Logging
from helpers.cli import CLI
from helpers.config import Config


from lib.worker import Worker
from lib.version import __version__


logger = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"

instances: List[Worker] = []


# ======================================================================


async def main(config: Dict) -> None:
    storage = config["storage"]
    for station in config["stations"]:
        worker = await Worker.create(storage, **station)
        instances.append(worker)

    if not instances:
        raise RuntimeError("No stations configured")


# ======================================================================


@CLI.handler("daemon")
def daemon(**kwargs: Dict) -> None:
    # Thanks to https://github.com/cjrh/aiorun for code below
    def _shutdown_handler(loop):
        loop.remove_signal_handler(SIGTERM)
        loop.add_signal_handler(SIGINT, lambda: None)
        loop.stop()

    logging.getLogger("asyncio").setLevel(logging.WARNING)

    try:
        import uvloop

        uvloop.install()
    except ImportError:
        pass

    loop = asyncio.get_event_loop()

    config = kwargs["config"]
    loop.create_task(main(config))

    loop.add_signal_handler(SIGINT, _shutdown_handler, loop)
    loop.add_signal_handler(SIGTERM, _shutdown_handler, loop)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    tasks = asyncio.all_tasks(loop)
    for task in tasks:
        task.cancel()
    for instance in instances:
        tasks.add(instance.close())

    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
    if not WINDOWS:
        loop.close()


# ======================================================================


if __name__ == "__main__":
    config = Config()
    Logging.configure(config.get("logs"))

    CLI.dispatch(__doc__, __version__, config=config)
