import asyncio
import logging
import os
import io
from typing import Optional, Union

import aiohttp

from helpers.utils import (
    AIOClassFactory,
    duration_to_seconds,
    unix_timestamp,
    format_timestamp,
    interval_representation,
)

logger = logging.getLogger(__name__)


class Worker(AIOClassFactory):
    BUFFER_SIZE = 20 * 1024 * 1024

    def __init__(
        self, storage: str, title: str, url: str, duration: Union[str, int] = 3600
    ) -> None:
        self._logger = logging.LoggerAdapter(
            logger.getChild(self.__class__.__name__), extra={"station": title}
        )

        self._storage = storage.replace("{station}", title)

        self._title = title
        self._url = url
        self._duration = duration_to_seconds(duration)

        self._buffer = io.BytesIO()

        self._worker_task_object: Optional[asyncio.Task] = None

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(sock_read=5),
            headers={"Icy-MetaData": "1"},
        )

    async def _parse_metadata_title(self, metadata: bytes) -> Optional[str]:
        for k, v in [x.split("=") for x in metadata.decode().split(";") if "=" in x]:
            if k == "StreamTitle":
                title = v.strip("'").strip()
                if title != "-":
                    return title
            break
        return None

    async def _worker_task(self) -> None:
        if not os.path.exists(self._storage):
            os.makedirs(self._storage, mode=0o755, exist_ok=True)

        while True:
            try:
                await self._worker()
                continue  # creating a new file
            except asyncio.exceptions.CancelledError:
                break
            except (
                aiohttp.client_exceptions.ServerTimeoutError,
                aiohttp.client_exceptions.ClientConnectorError,
            ) as e:
                self._logger.warning(e)
            except RuntimeError as e:
                self._logger.error(e)
                break
            except BaseException as e:
                self._logger.exception("", exc_info=e)

            await asyncio.sleep(60)
        await self.close()

    async def _worker(self) -> None:
        async with self._session.request("GET", self._url) as response:
            started_at = unix_timestamp()
            filename = "{} {}".format(self._title, format_timestamp(started_at, "%Y%m%d-%H%M%S"))

            content_type = response.headers.get("Content-Type")
            if content_type == "audio/mpeg":
                fileext = "mp3"
            elif content_type == "application/aacp" or content_type == "audio/aacp":
                fileext = "aac"
            elif content_type == "application/ogg" or content_type == "audio/ogg":
                fileext = "ogg"
            elif content_type == "audio/x-mpegurl":
                raise RuntimeError("M3U playlists are currently not supported")
            else:
                raise RuntimeError("Unknown content-type: {}".format(content_type))

            metadata_interval = int(response.headers.get("icy-metaint", 0))
            if metadata_interval:
                counter = 0

                # fmt: off
                with open("{}/{}.{}".format(self._storage, filename, fileext), mode="wb", buffering=self.BUFFER_SIZE) as media_fd, open("{}/{}.cue".format(self._storage, filename), mode="w") as cue_fd: # noqa E501
                    # fmt: on

                    self._logger.info("New file started: {}.{} (with CUE)".format(filename, fileext)) # noqa E501

                    cue_fd.write("TITLE \"{}\"\n".format(filename))
                    cue_fd.write("FILE \"{}.{}\" {}\n".format(filename, fileext, fileext.upper()))

                    while not response.content.at_eof():
                        media_fd.write(await response.content.readexactly(metadata_interval))

                        if unix_timestamp() - started_at >= self._duration:
                            return  # rotation by duration

                        # Get number of blocks with meta information
                        metadata_blocks = int.from_bytes(
                            await response.content.readexactly(1), byteorder="big"
                        )
                        if metadata_blocks > 0:
                            # Read meta information (each block == 16 bytes)
                            metadata = await response.content.readexactly(metadata_blocks * 16)
                            title = await self._parse_metadata_title(metadata)
                            if title:
                                time_passed = unix_timestamp() - started_at

                                self._logger.debug(
                                    "- {:02}:{:02}:{:02}:{:02} {}".format(
                                        *interval_representation(time_passed),
                                        title
                                    )
                                )
                                counter += 1
                                cue_fd.write("  TRACK {:02} AUDIO\n".format(counter))
                                cue_fd.write("    TITLE \"{}\"\n".format(title))
                                cue_fd.write("    INDEX 01 {:02}:{:02}:00\n".format(*divmod(time_passed, 60))) # noqa E501
            else:
                with open(self._storage + "/" + filename + "." + fileext, mode="wb", buffering=self.BUFFER_SIZE) as media_fd: # noqa E501
                    self._logger.info("New file started: {}.{} (without CUE)".format(filename, fileext)) # noqa E501

                    while not response.content.at_eof():
                        media_fd.write(await response.content.readany())
                        if unix_timestamp() - started_at >= self._duration:
                            return  # rotation by duration

    async def init(self) -> None:
        self._logger.debug("Started...")
        self._worker_task_object = asyncio.create_task(self._worker_task())

    async def close(self) -> None:
        if self._worker_task_object:
            self._worker_task_object.cancel()
            self._worker_task_object = None
        await self._session.close()
        self._logger.debug("Stopped.")
