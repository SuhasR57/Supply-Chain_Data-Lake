resource "aws_athena_workgroup" "lake" {
  name        = "scdl-dev"
  description = "Query published supply chain datasets"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    bytes_scanned_cutoff_per_query = 104857600

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake["athena-results"].id}/queries/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}