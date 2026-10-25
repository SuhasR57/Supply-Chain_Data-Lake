data "aws_caller_identity" "current" {}

locals {
  bucket_purposes = toset([
    "raw",
    "curated",
    "quarantine",
    "athena-results",
  ])

  bucket_prefix = "scdl-dev-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

resource "aws_s3_bucket" "lake" {
  for_each = local.bucket_purposes

  bucket        = "${local.bucket_prefix}-${each.key}"
  force_destroy = false

  tags = {
    Purpose = each.key
  }
}

resource "aws_s3_bucket_public_access_block" "lake" {
  for_each = aws_s3_bucket.lake

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  for_each = aws_s3_bucket.lake

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}