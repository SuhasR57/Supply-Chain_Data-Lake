"""Register one published batch in the Glue Data Catalog."""

import argparse
import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from src.catalog_registrar import register_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--curated-bucket", required=True)
    parser.add_argument("--database", required=True)

    parser.add_argument(
        "--profile",
        default="supplychain",
    )

    parser.add_argument(
        "--region",
        default="us-east-2",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and verify AWS metadata without creating partitions",
    )

    args = parser.parse_args()

    try:
        session = boto3.Session(
            profile_name=args.profile,
            region_name=args.region,
        )

        result = register_batch(
            batch_id=args.batch_id,
            s3=session.client("s3"),
            glue=session.client("glue"),
            curated_bucket=args.curated_bucket,
            database=args.database,
            dry_run=args.dry_run,
        )

        print(json.dumps(result, indent=2))

    except (
        BotoCoreError,
        ClientError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
    ) as error:
        parser.exit(1, f"Registration failed: {error}\n")


if __name__ == "__main__":
    main()