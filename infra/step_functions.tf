locals {
  batch_workflow_name = "scdl-dev-process-batch"

  batch_workflow_arn = "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.batch_workflow_name}"
}

resource "aws_iam_role" "batch_workflow" {
  name = "scdl-dev-batch-workflow-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "states.amazonaws.com"
        }

        Action = "sts:AssumeRole"

        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }

          ArnEquals = {
            "aws:SourceArn" = local.batch_workflow_arn
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "batch_workflow_invoke" {
  name = "scdl-dev-batch-workflow-invoke"
  role = aws_iam_role.batch_workflow.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.transform.arn
      }
    ]
  })
}

resource "aws_sfn_state_machine" "batch" {
  name     = local.batch_workflow_name
  role_arn = aws_iam_role.batch_workflow.arn
  type     = "STANDARD"

  definition = templatefile(
    "${path.module}/workflows/process_batch.asl.json",
    {
      transform_function_arn = aws_lambda_function.transform.arn
      batch_runs_table_name  = aws_dynamodb_table.batch_runs.name
    }
  )

  depends_on = [
    aws_iam_role_policy.batch_workflow_invoke,
    aws_iam_role_policy.batch_workflow_ledger,
  ]
}