"""Lambda entry point for the initial cloud pipeline check."""

import platform
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pyarrow as pa

import logging
import os

import boto3

from src.s3_pipeline import process_batch

from scripts.generate_batches import generate_batches
from scripts.validate_batch import validate_batch
from scripts.transform_batch import transform_batch


def run_sample(event, context):
    if event.get("mode") != "sample":
        raise ValueError(
            "This initial deployment supports mode='sample' only"
        )

    sample_dir = (
        Path(__file__).resolve().parent / "data" / "sample"
    )

    # Lambda's writable working area is /tmp.
    with TemporaryDirectory(dir="/tmp") as temporary:
        workspace = Path(temporary)

        generate_batches(
            sample_dir,
            workspace / "batches",
            date(2018, 1, 1),
            1,
        )

        batch_id = "olist-2018-01-01"

        validated_dir, _validation_report = validate_batch(
            workspace / "batches" / batch_id,
            workspace / "validated",
        )

        _parquet_dir, transform_report = transform_batch(
            validated_dir,
            workspace / "parquet",
        )

        return {
            "status": "ok",
            "mode": "sample",
            "batch_id": batch_id,
            "versions": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "pyarrow": pa.__version__,
            },
            "rows": {
                name: details["rows"]
                for name, details
                in transform_report["datasets"].items()
            },
        }

def handler(event, context):
    logging.getLogger().setLevel(logging.INFO)

    if not isinstance(event, dict):
        raise ValueError("Expected an event object")

    if event.get("mode") == "sample":
        return run_sample(event, context)

    if event.get("mode") == "s3":
        buckets = {
            "raw": os.environ["RAW_BUCKET"],
            "curated": os.environ["CURATED_BUCKET"],
            "quarantine": os.environ["QUARANTINE_BUCKET"],
        }

        return process_batch(
            event.get("batch_id"),
            boto3.client("s3"),
            buckets,
            temporary_root="/tmp",
        )

    raise ValueError("Supported modes: sample, s3")