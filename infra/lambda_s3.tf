resource "aws_iam_role_policy" "transform_s3" {
  name = "scdl-dev-transform-s3"
  role = aws_iam_role.transform.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "ReadRawBatches"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.lake["raw"].arn}/batches/*"
      },
      {
        Sid      = "ReadCompletionManifests"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.lake["curated"].arn}/manifests/*"
      },
      {
        Sid      = "CheckMissingCompletionManifests"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.lake["curated"].arn
      },
      {
        Sid    = "WriteCuratedRunsAndManifests"
        Effect = "Allow"
        Action = ["s3:PutObject"]

        Resource = [
          "${aws_s3_bucket.lake["curated"].arn}/runs/*",
          "${aws_s3_bucket.lake["curated"].arn}/manifests/*",
        ]
      },
      {
        Sid      = "WriteQuarantineRuns"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.lake["quarantine"].arn}/runs/*"
      },
    ]
  })
}