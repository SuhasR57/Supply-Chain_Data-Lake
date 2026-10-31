locals {
  transform_function_name = "scdl-dev-transform"
}

resource "aws_cloudwatch_log_group" "transform" {
  name              = "/aws/lambda/${local.transform_function_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "transform" {
  name = "scdl-dev-transform-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "transform_logs" {
  name = "scdl-dev-transform-logs"
  role = aws_iam_role.transform.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]

        Resource = "${aws_cloudwatch_log_group.transform.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "transform" {
  function_name = local.transform_function_name
  description   = "Supply chain validation and Parquet transformation"

  role    = aws_iam_role.transform.arn
  handler = "lambda_handler.handler"

  runtime       = "python3.12"
  architectures = ["x86_64"]

  filename = "${path.module}/build/transform.zip"
  source_code_hash = filebase64sha256(
    "${path.module}/build/transform.zip"
  )

  memory_size = 1024
  timeout     = 120

  layers = [
    "arn:aws:lambda:us-east-2:336392948345:layer:AWSSDKPandas-Python312:32"
  ]

  depends_on = [
    aws_iam_role_policy.transform_logs,
    aws_iam_role_policy.transform_s3,
  ]

  environment {
    variables = {
      RAW_BUCKET        = aws_s3_bucket.lake["raw"].id
      CURATED_BUCKET    = aws_s3_bucket.lake["curated"].id
      QUARANTINE_BUCKET = aws_s3_bucket.lake["quarantine"].id
    }
  }

}