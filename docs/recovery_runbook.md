# Recovery Runbook

## Failed batch

1. Find the execution ARN and batch ID.
2. Inspect the failed task and Lambda logs.
3. Check the raw manifest and referenced source objects.
4. Correct the underlying problem.
5. Start a new execution for the same batch.
6. Verify workflow success and catalog registration.
7. Compare Athena counts with the completion manifest.
8. Preserve the original failed attempt in the ledger.

## Publication succeeded but registration failed

1. Confirm the curated completion manifest exists.
2. Inspect the registration error.
3. Correct catalog permissions or configuration.
4. Start a new execution for the same batch.
5. Verify processing returns `already_processed`.
6. Verify all three partitions match committed locations.

## Interrupted execution

1. Confirm the execution status in Step Functions.
2. Preview reconciliation for its exact batch and execution ARN.
3. Review any proposed ledger change.
4. Apply reconciliation when appropriate.
5. Inspect publication and catalog state separately.
6. Start a new execution if the batch still needs recovery.

## Undelivered trigger event

1. Inspect the SQS dead-letter message and error attributes.
2. Identify the batch from the event and verify its raw manifest.
3. Correct the EventBridge target, role, or delivery configuration.
4. Start a new workflow execution for the verified batch.
5. Verify publication, registration, ledger outcome, and Athena counts.
6. Delete only the successfully recovered message using its current receipt handle.

## Recovery evidence

Record:
- Original and recovery execution ARNs.
- Failure cause and correction.
- Completion manifest key and run ID.
- Glue partition locations.
- Athena query ID and reconciled row counts.
- Reconciliation preview and applied result, if used.