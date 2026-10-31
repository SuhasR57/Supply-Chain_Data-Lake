"""Publish completed local output, tolerating brief Windows file locks."""

import time
from pathlib import Path


def publish_directory(source, destination):
    source = Path(source)
    destination = Path(destination)

    for attempt in range(7):
        if destination.exists():
            raise FileExistsError(
                f"Completed output already exists: {destination}"
            )

        try:
            source.rename(destination)
            return

        except PermissionError as error:
            if destination.exists():
                raise FileExistsError(
                    f"Completed output already exists: {destination}"
                ) from error

            if (
                getattr(error, "winerror", None) not in {5, 32}
                or attempt == 6
            ):
                raise

            time.sleep(min(0.05 * (2 ** attempt), 1.0))