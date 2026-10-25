variable "aws_region" {
  description = "AWS region containing the project resources."
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "Local AWS profile used to deploy the project."
  type        = string
  default     = "supplychain"
}