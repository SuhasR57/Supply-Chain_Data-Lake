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