# Build roadmap

1. Workspace, source data exploration, and project documentation.
2. Terraform foundation: S3 storage, access permissions, and budget awareness.
3. Daily batch generator, manifests, and Python uploader.
4. Schema and record validation; quarantine with reasons.
5. Parquet transformations and Lambda deployment.
6. Step Functions orchestration, retries, and failure paths.
7. Manifest-triggered ingestion and DynamoDB duplicate prevention.
8. Glue catalog tables, date partitions, and Athena checks.
9. Failed-batch recovery, historical reprocessing, logs, and alarms.
10. Fresh deployment verification, acceptance demo, and cleanup guide.

## Final acceptance cases

- A valid batch becomes queryable.
- Missing required files prevent publication.
- Invalid records are quarantined with reasons.
- Duplicate manifest submissions do not duplicate published data.
- Interrupted processing can be recovered safely.
- Historical batches can be processed and reconciled.
