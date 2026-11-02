resource "aws_cloudwatch_event_rule" "raw_manifest" {
  name        = "scdl-dev-raw-manifest"
  description = "Start batch processing when a raw manifest is created"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]

    detail = {
      bucket = {
        name = [aws_s3_bucket.lake["raw"].id]
      }

      object = {
        key = [
          {
            wildcard = "batches/olist-*/manifest.json"
          }
        ]
      }
    }
  })
}

resource "aws_iam_role" "raw_manifest_events" {
  name = "scdl-dev-raw-manifest-events-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "events.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "raw_manifest_start_workflow" {
  name = "scdl-dev-raw-manifest-start-workflow"
  role = aws_iam_role.raw_manifest_events.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = aws_sfn_state_machine.batch.arn
      }
    ]
  })
}

resource "aws_sqs_queue" "raw_manifest_dlq" {
  name = "scdl-dev-raw-manifest-dlq"

  message_retention_seconds = 345600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue_policy" "raw_manifest_dlq" {
  queue_url = aws_sqs_queue.raw_manifest_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowEventBridgeDelivery"
        Effect = "Allow"

        Principal = {
          Service = "events.amazonaws.com"
        }

        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.raw_manifest_dlq.arn

        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_cloudwatch_event_rule.raw_manifest.arn
          }

          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_event_target" "raw_manifest_workflow" {
  rule      = aws_cloudwatch_event_rule.raw_manifest.name
  target_id = "ProcessBatch"

  arn      = aws_sfn_state_machine.batch.arn
  role_arn = aws_iam_role.raw_manifest_events.arn

  input_transformer {
    input_paths = {
      manifest_key = "$.detail.object.key"
    }

    input_template = <<-JSON
      {
        "raw_manifest_key": <manifest_key>
      }
    JSON
  }

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }

  dead_letter_config {
    arn = aws_sqs_queue.raw_manifest_dlq.arn
  }

  depends_on = [
    aws_iam_role_policy.raw_manifest_start_workflow,
    aws_sqs_queue_policy.raw_manifest_dlq,
  ]
}

resource "aws_s3_bucket_notification" "raw_eventbridge" {
  bucket      = aws_s3_bucket.lake["raw"].id
  eventbridge = true

  depends_on = [
    aws_cloudwatch_event_target.raw_manifest_workflow,
  ]
}

