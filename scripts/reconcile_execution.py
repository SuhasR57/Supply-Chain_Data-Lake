"""Reconcile one interrupted execution; preview unless --apply is supplied."""

import argparse
import json
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError


TERMINAL_FAILURES = {
    "FAILED": "failed",
    "ABORTED": "aborted",
    "TIMED_OUT": "timed_out",
}


def reconcile(
    table,
    sfn,
    batch_id,
    execution_arn,
    workflow_arn,
    apply=False,
):
    execution = sfn.describe_execution(
        executionArn=execution_arn
    )

    if execution["stateMachineArn"] != workflow_arn:
        raise ValueError(
            "Execution belongs to a different workflow"
        )

    original = json.loads(execution["input"])

    if "raw_manifest_key" in original:
        matches = (
            original["raw_manifest_key"]
            == f"batches/{batch_id}/manifest.json"
        )
    else:
        matches = original.get("batch_id") == batch_id

    if not matches:
        raise ValueError(
            "Execution input does not match the requested batch"
        )

    key = {
        "batch_id": batch_id,
        "execution_id": execution_arn,
    }

    item = table.get_item(
        Key=key,
        ConsistentRead=True,
    ).get("Item")

    result = {
        **key,
        "workflow_status": execution["status"],
        "ledger_status": item.get("status") if item else None,
    }

    if execution.get("redriveCount", 0) > 0:
        return {
            **result,
            "action": "review_redriven_execution",
        }

    if item is None:
        return {
            **result,
            "action": "no_ledger_record",
        }

    if item.get("status") != "running":
        return {
            **result,
            "action": "leave_existing_outcome",
        }

    if execution["status"] in {"RUNNING", "PENDING_REDRIVE"}:
        return {
            **result,
            "action": "leave_active_execution",
        }

    if (
        execution["status"] not in TERMINAL_FAILURES
        or not item.get("started_at")
    ):
        return {
            **result,
            "action": "manual_review_required",
        }

    target = TERMINAL_FAILURES[execution["status"]]
    result["proposed_status"] = target

    if not apply:
        return {
            **result,
            "action": "would_update",
        }

    # Recheck execution state immediately before writing.
    latest = sfn.describe_execution(
        executionArn=execution_arn
    )

    if (
        latest["status"] != execution["status"]
        or latest.get("redriveCount", 0)
        != execution.get("redriveCount", 0)
        or latest.get("stopDate") != execution.get("stopDate")
    ):
        return {
            **result,
            "action": "execution_changed_retry_later",
        }

    try:
        table.update_item(
            Key=key,
            ConditionExpression=(
                "attribute_exists(batch_id) "
                "AND attribute_exists(execution_id) "
                "AND #status = :running "
                "AND started_at = :started"
            ),
            UpdateExpression=(
                "SET #status = :target, "
                "finished_at = :finished, "
                "workflow_status = :workflow, "
                "reconciled_at = :now, "
                "#error = :error"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "error",
            },
            ExpressionAttributeValues={
                ":running": "running",
                ":started": item["started_at"],
                ":target": target,
                ":finished": execution["stopDate"].isoformat(),
                ":workflow": execution["status"],
                ":now": datetime.now(timezone.utc).isoformat(),
                ":error": (
                    execution.get("error")
                    or f"Execution{execution['status']}"
                ),
            },
        )

    except ClientError as error:
        if (
            error.response["Error"]["Code"]
            == "ConditionalCheckFailedException"
        ):
            return {
                **result,
                "action": "ledger_changed_no_update",
            }

        raise

    return {
        **result,
        "action": "updated",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--execution-arn", required=True)
    parser.add_argument("--workflow-arn", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--profile", default="supplychain")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    try:
        session = boto3.Session(
            profile_name=args.profile,
            region_name=args.region,
        )

        result = reconcile(
            table=session.resource("dynamodb").Table(args.table),
            sfn=session.client("stepfunctions"),
            batch_id=args.batch_id,
            execution_arn=args.execution_arn,
            workflow_arn=args.workflow_arn,
            apply=args.apply,
        )

        print(json.dumps(result, indent=2))

    except (
        BotoCoreError,
        ClientError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        parser.exit(1, f"Reconciliation failed: {error}\n")


if __name__ == "__main__":
    main()