variable "alert_email" {
  description = "Email receiving project alerts; empty disables the subscription."
  type        = string
  default     = ""
}

resource "aws_sns_topic" "pipeline_alerts" {
  name = "scdl-dev-pipeline-alerts"
}

resource "aws_sns_topic_policy" "pipeline_alerts" {
  arn = aws_sns_topic.pipeline_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "AllowProjectCloudWatchAlarms"
        Effect = "Allow"

        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }

        Action   = "sns:Publish"
        Resource = aws_sns_topic.pipeline_alerts.arn

        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }

          ArnLike = {
            "aws:SourceArn" = "arn:aws:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:scdl-dev-*"
          }
        }
      }
    ]
  })
}

resource "aws_sns_topic_subscription" "pipeline_email" {
  count = trimspace(var.alert_email) == "" ? 0 : 1

  topic_arn = aws_sns_topic.pipeline_alerts.arn
  protocol  = "email"
  endpoint  = trimspace(var.alert_email)
}

locals {
  pipeline_alarm_specs = merge(
    {
      for outcome, metric in {
        failed    = "ExecutionsFailed"
        timed-out = "ExecutionsTimedOut"
        aborted   = "ExecutionsAborted"
      } :

      "workflow-${outcome}" => {
        namespace   = "AWS/States"
        metric_name = metric
        statistic   = "Sum"

        dimensions = {
          StateMachineArn = aws_sfn_state_machine.batch.arn
        }
      }
    },
    {
      trigger-dlq-backlog = {
        namespace   = "AWS/SQS"
        metric_name = "ApproximateNumberOfMessagesVisible"
        statistic   = "Maximum"

        dimensions = {
          QueueName = aws_sqs_queue.raw_manifest_dlq.name
        }
      }

      trigger-dlq-delivery-failed = {
        namespace   = "AWS/Events"
        metric_name = "InvocationsFailedToBeSentToDlq"
        statistic   = "Sum"

        dimensions = {
          RuleName = aws_cloudwatch_event_rule.raw_manifest.name
        }
      }
    }
  )
}

resource "aws_cloudwatch_metric_alarm" "pipeline" {
  for_each = local.pipeline_alarm_specs

  alarm_name        = "scdl-dev-${each.key}"
  alarm_description = "Supply chain pipeline: ${each.key}. Inspect workflow history or trigger delivery."

  namespace   = each.value.namespace
  metric_name = each.value.metric_name
  statistic   = each.value.statistic
  dimensions  = each.value.dimensions

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1

  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]
  ok_actions    = [aws_sns_topic.pipeline_alerts.arn]

  depends_on = [
    aws_sns_topic_policy.pipeline_alerts,
  ]
}