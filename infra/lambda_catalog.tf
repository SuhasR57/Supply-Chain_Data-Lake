resource "aws_iam_role_policy" "transform_catalog" {
  name = "scdl-dev-transform-catalog"
  role = aws_iam_role.transform.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ReadCommittedParquetMetadata"
        Effect = "Allow"
        Action = ["s3:GetObject"]

        Resource = "${aws_s3_bucket.lake["curated"].arn}/runs/*"
      },
      {
        Sid    = "RegisterDatasetPartitions"
        Effect = "Allow"

        Action = [
          "glue:GetTable",
          "glue:GetPartition",
          "glue:CreatePartition",
        ]

        Resource = concat(
          [
            "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
            aws_glue_catalog_database.lake.arn,
          ],
          [
            for table in values(aws_glue_catalog_table.lake) :
            table.arn
          ]
        )
      },
    ]
  })
}