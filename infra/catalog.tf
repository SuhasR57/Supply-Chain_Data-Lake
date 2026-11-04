locals {
  catalog_schemas = {
    orders = [
      {
        name = "order_id"
        type = "string"
      },
      {
        name = "customer_id"
        type = "string"
      },
      {
        name = "order_status"
        type = "string"
      },
      {
        name = "order_purchase_timestamp"
        type = "timestamp"
      },
      {
        name = "order_approved_at"
        type = "timestamp"
      },
      {
        name = "order_delivered_carrier_date"
        type = "timestamp"
      },
      {
        name = "order_delivered_customer_date"
        type = "timestamp"
      },
      {
        name = "order_estimated_delivery_date"
        type = "timestamp"
      },
    ]

    order_items = [
      {
        name = "order_id"
        type = "string"
      },
      {
        name = "order_item_id"
        type = "bigint"
      },
      {
        name = "product_id"
        type = "string"
      },
      {
        name = "seller_id"
        type = "string"
      },
      {
        name = "shipping_limit_date"
        type = "timestamp"
      },
      {
        name = "price"
        type = "decimal(18,2)"
      },
      {
        name = "freight_value"
        type = "decimal(18,2)"
      },
    ]

    shipments = [
      {
        name = "order_id"
        type = "string"
      },
      {
        name = "order_status"
        type = "string"
      },
      {
        name = "carrier_handoff_at"
        type = "timestamp"
      },
      {
        name = "customer_delivered_at"
        type = "timestamp"
      },
      {
        name = "estimated_delivery_at"
        type = "timestamp"
      },
    ]
  }
}

resource "aws_glue_catalog_database" "lake" {
  name        = "scdl_dev"
  description = "Published supply chain batch replay datasets"
}

resource "aws_glue_catalog_table" "lake" {
  for_each = local.catalog_schemas

  name          = each.key
  database_name = aws_glue_catalog_database.lake.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL       = "TRUE"
    classification = "parquet"
  }

  partition_keys {
    name = "source_date"
    type = "string"
  }

  storage_descriptor {
    location = "s3://${aws_s3_bucket.lake["curated"].id}/catalog_roots/${each.key}/"

    input_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"

    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = each.value

      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}