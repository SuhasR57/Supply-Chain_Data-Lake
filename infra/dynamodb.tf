resource "aws_dynamodb_table" "batch_runs" {
  name         = "scdl-dev-batch-runs"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "batch_id"
  range_key = "execution_id"

  attribute {
    name = "batch_id"
    type = "S"
  }

  attribute {
    name = "execution_id"
    type = "S"
  }
}

resource "aws_iam_role_policy" "batch_workflow_ledger" {
  name = "scdl-dev-batch-workflow-ledger"
  role = aws_iam_role.batch_workflow.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Action = [
          "dynamodb:UpdateItem",
        ]

        Resource = aws_dynamodb_table.batch_runs.arn
      }
    ]
  })
}