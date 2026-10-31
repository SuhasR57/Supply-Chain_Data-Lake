import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.local_storage import publish_directory


class TestLocalStorage(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.root = Path(self.temporary.name)
        self.source = self.root / "staging"
        self.source.mkdir()

        (self.source / "report.json").write_text(
            "complete",
            encoding="utf-8",
        )

        self.destination = self.root / "published"

    @staticmethod
    def locked():
        error = PermissionError(
            "Simulated Windows sharing lock"
        )
        error.winerror = 32
        return error

    def test_transient_windows_lock_is_retried(self):
        original = Path.rename
        calls = []

        def rename(source, destination):
            calls.append(1)

            if len(calls) <= 2:
                raise self.locked()

            return original(source, destination)

        with (
            patch.object(
                Path,
                "rename",
                autospec=True,
                side_effect=rename,
            ),
            patch("src.local_storage.time.sleep") as sleep,
        ):
            publish_directory(
                self.source,
                self.destination,
            )

        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(
            (self.destination / "report.json").read_text(),
            "complete",
        )

    def test_existing_output_is_preserved(self):
        self.destination.mkdir()

        (self.destination / "report.json").write_text(
            "original",
            encoding="utf-8",
        )

        with self.assertRaises(FileExistsError):
            publish_directory(
                self.source,
                self.destination,
            )

        self.assertEqual(
            (self.destination / "report.json").read_text(),
            "original",
        )
        self.assertTrue(self.source.exists())

    def test_persistent_lock_has_bounded_retries(self):
        with (
            patch.object(
                Path,
                "rename",
                side_effect=self.locked(),
            ) as rename,
            patch("src.local_storage.time.sleep") as sleep,
        ):
            with self.assertRaises(PermissionError):
                publish_directory(
                    self.source,
                    self.destination,
                )

        self.assertEqual(rename.call_count, 7)
        self.assertEqual(sleep.call_count, 6)

    def test_other_permission_errors_are_not_retried(self):
        with (
            patch.object(
                Path,
                "rename",
                side_effect=PermissionError("Denied"),
            ) as rename,
            patch("src.local_storage.time.sleep") as sleep,
        ):
            with self.assertRaises(PermissionError):
                publish_directory(
                    self.source,
                    self.destination,
                )

        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()