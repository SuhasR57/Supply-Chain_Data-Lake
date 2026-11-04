output "bucket_names" {
  description = "Project bucket names, indexed by purpose."

  value = {
    for purpose, bucket in aws_s3_bucket.lake :
    purpose => bucket.id
  }
}

output "raw_bucket_name" {
  description = "Bucket receiving source data and manifests."
  value       = aws_s3_bucket.lake["raw"].id
}

output "transform_function_name" {
  description = "Lambda function running the transformation pipeline."
  value       = aws_lambda_function.transform.function_name
}

output "batch_workflow_arn" {
  description = "Step Functions workflow processing one batch."
  value       = aws_sfn_state_machine.batch.arn
}

output "batch_workflow_definition" {
  description = "Rendered workflow definition for validation."
  value       = aws_sfn_state_machine.batch.definition
}

output "batch_runs_table_name" {
  description = "DynamoDB table containing workflow attempt history."
  value       = aws_dynamodb_table.batch_runs.name
}

output "raw_manifest_rule_name" {
  description = "EventBridge rule starting raw batch processing."
  value       = aws_cloudwatch_event_rule.raw_manifest.name
}

output "raw_manifest_dlq_url" {
  description = "Queue holding undelivered workflow trigger events."
  value       = aws_sqs_queue.raw_manifest_dlq.url
}

output "glue_database_name" {
  description = "Glue database containing the published datasets."
  value       = aws_glue_catalog_database.lake.name
}

output "glue_table_names" {
  description = "Glue tables for the published datasets."

  value = {
    for dataset, table in aws_glue_catalog_table.lake :
    dataset => table.name
  }
}

output "athena_workgroup_name" {
  description = "Athena workgroup for project queries."
  value       = aws_athena_workgroup.lake.name
}