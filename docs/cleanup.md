# Cleanup

## Preserve Evidence

Before deleting resources, save:

- Release verification notes and screenshots.
- Completion manifests and useful query results.
- Any required source or output data.
- A private backup of Terraform state.

## Review Resources

Confirm the AWS account, region, and Terraform-managed resource names.

Stop new uploads and disable the project's EventBridge rule before
removing pipeline resources. Let active executions finish or investigate
their outcomes.

## Data Removal

The project uses `force_destroy = false` for its S3 buckets.

Before deleting a bucket, review and explicitly remove the project
objects it contains. If versioning has been enabled, include object
versions and delete markers.

Export any required DynamoDB execution history before deleting its table.

## Terraform Removal

Create and inspect a destroy plan:

    terraform "-chdir=infra" plan -destroy "-out=cleanup.tfplan"

Apply the reviewed plan only when the project resources and data are
ready for deletion.

After removal, verify the project resources are gone and review billing
for remaining resources.

Logging out of the AWS CLI does not remove resources or stop their charges.