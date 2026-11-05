import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from botocore.exceptions import ClientError

from scripts.reconcile_execution import reconcile


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.table = Mock()

        self.table.get_item.return_value = {
            "Item": {
                "status": "running",
                "started_at": "2026-11-04T00:00:00+00:00",
            }
        }

        self.sfn = Mock()

        self.execution = {
            "stateMachineArn": "test-workflow",
            "input": json.dumps({
                "batch_id": "olist-2018-01-11"
            }),
            "status": "ABORTED",
            "stopDate": datetime(
                2026, 11, 4, tzinfo=timezone.utc
            ),
        }

        self.sfn.describe_execution.return_value = self.execution

    def run_case(self, apply=False):
        return reconcile(
            self.table,
            self.sfn,
            "olist-2018-01-11",
            "test-execution",
            "test-workflow",
            apply=apply,
        )

    def test_preview_never_writes(self):
        self.assertEqual(
            self.run_case()["action"],
            "would_update",
        )
        self.table.update_item.assert_not_called()

    def test_active_execution_is_not_changed(self):
        self.execution["status"] = "RUNNING"

        self.assertEqual(
            self.run_case(True)["action"],
            "leave_active_execution",
        )
        self.table.update_item.assert_not_called()

    def test_existing_success_is_preserved(self):
        self.table.get_item.return_value["Item"]["status"] = (
            "complete"
        )

        self.assertEqual(
            self.run_case(True)["action"],
            "leave_existing_outcome",
        )
        self.table.update_item.assert_not_called()

    def test_all_failure_states_map_correctly(self):
        cases = [
            ("ABORTED", "aborted"),
            ("TIMED_OUT", "timed_out"),
            ("FAILED", "failed"),
        ]

        for state, expected in cases:
            with self.subTest(state=state):
                self.execution["status"] = state

                self.assertEqual(
                    self.run_case(True)["action"],
                    "updated",
                )

                values = (
                    self.table.update_item.call_args.kwargs[
                        "ExpressionAttributeValues"
                    ]
                )

                self.assertEqual(values[":target"], expected)

    def test_concurrent_ledger_change_is_not_overwritten(self):
        self.table.update_item.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException"
                }
            },
            "UpdateItem",
        )

        self.assertEqual(
            self.run_case(True)["action"],
            "ledger_changed_no_update",
        )

    def test_wrong_workflow_is_rejected(self):
        self.execution["stateMachineArn"] = "other-workflow"

        with self.assertRaises(ValueError):
            self.run_case(True)

        self.table.update_item.assert_not_called()

    def test_changed_execution_is_not_written(self):
        changed = copy.deepcopy(self.execution)
        changed["status"] = "RUNNING"

        self.sfn.describe_execution.side_effect = [
            self.execution,
            changed,
        ]

        self.assertEqual(
            self.run_case(True)["action"],
            "execution_changed_retry_later",
        )
        self.table.update_item.assert_not_called()

    def test_missing_row_is_not_created(self):
        self.table.get_item.return_value = {}

        self.assertEqual(
            self.run_case(True)["action"],
            "no_ledger_record",
        )
        self.table.update_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()