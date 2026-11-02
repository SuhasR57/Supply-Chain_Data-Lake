# Supply Chain Data Lake

An AWS data engineering project that replays historical order data as daily batches, verifies file integrity, and publishes raw files to S3 using manifests.

## Technology Stack

- Python, pandas, and Boto3
- Amazon S3
- Terraform
- AWS Region: Ohio (`us-east-2`)

## Current Features

- Inspect Olist order and order-item datasets.
- Generate daily CSV batches and JSON manifests.
- Verify file sizes, SHA-256 hashes, and row counts.
- Upload data files before publishing the manifest.
- Skip already published batch IDs.

## Architecture

```text
Historical CSVs
      ↓
Batch generator → Raw S3 files + manifest
                              ↓
                       Lambda invocation
                              ↓
                 Integrity checks and validation
                         ↙             ↘
                Quarantine          Accepted records
                                         ↓
                                Parquet transformation
                                         ↓
                                   Curated S3 files
                                         ↓
                                 Completion manifest
```

Terraform manages infrastructure. CloudWatch stores function logs.

## Project Structure

```text
data/
  raw/          Downloaded Olist files
  sample/       Synthetic examples
  local/        Generated batches and reports
scripts/        Inspection, generation, and upload tools
infra/          Terraform configuration
docs/           Data notes and architecture
src/            Future processing modules
sql/            Future Athena queries
tests/          Future automated tests
```

## Architecture

```mermaid
flowchart TD
    SOURCE["Olist historical CSV files"] --> GENERATOR["Python batch generator"]
    GENERATOR --> LOCAL["Daily CSV batches and manifests"]
    LOCAL --> UPLOADER["Uploader: verify sizes, hashes, and row counts"]
    UPLOADER --> RAW["S3 raw bucket<br/>CSV files uploaded before manifest"]

    MANUAL["Manual workflow execution<br/>batch_id"] --> CHECK["Step Functions: check input"]
    CHECK -->|Valid input| TASK["Invoke processing Lambda<br/>Retry temporary invocation errors"]
    CHECK -->|Invalid input| INVALID["Execution failed"]

    RAW --> DOWNLOAD["Lambda: download manifest and referenced files"]
    TASK --> DOWNLOAD
    DOWNLOAD --> INTEGRITY["Verify file integrity"]
    INTEGRITY --> VALIDATE["Validate schemas and records"]

    VALIDATE --> ACCEPTED["Accepted orders and order items"]
    VALIDATE --> REJECTED["Rejected records with reasons"]

    ACCEPTED --> TRANSFORM["Create typed orders, items, and shipments"]
    TRANSFORM --> VERIFY["Write and verify Parquet files"]
    VERIFY --> CURATED["S3 curated bucket<br/>Unique processing-run directory"]

    REJECTED --> QUARANTINE["S3 quarantine bucket<br/>Rejected CSVs and validation report"]

    CURATED --> COMMIT["Publish completion manifest last"]
    QUARANTINE --> COMMIT

    COMMIT --> RESULT["Return complete"]
    DOWNLOAD -->|Matching completion already exists| SKIP["Return already_processed"]

    RESULT --> STATUS["Step Functions: check result"]
    SKIP --> STATUS
    STATUS --> SUCCESS["Execution succeeded"]
    TASK -->|Unhandled processing error| FAILED["Execution failed"]

    LAMBDA_LOGS["CloudWatch<br/>Lambda logs"] -.-> DOWNLOAD
    TERRAFORM["Terraform<br/>Buckets, roles, Lambda, workflow, and log group"] -.-> RAW
    TERRAFORM -.-> TASK
```

### Processing and Publication

- Step Functions coordinates one batch; validation, transformation, and publication run inside Lambda.
- Only files referenced by a completed manifest are considered published.
- Repeated processing of the same completed input returns `already_processed`.
- Failed attempts may leave unreferenced files without publishing a completion manifest.
- Workflow execution is currently manual. Automatic triggers, DynamoDB tracking, and Athena integration are planned.

## Setup

Requires Python 3.11+, AWS CLI v2, Terraform, and Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

aws login --profile supplychain-login
aws sts get-caller-identity --profile supplychain
```

Download the [Olist dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and place these files in `data/raw/`:

- `olist_orders_dataset.csv`
- `olist_order_items_dataset.csv`

## Run

Inspect source data:

```powershell
.\.venv\Scripts\python.exe scripts/inspect_data.py
```

Generate seven historical batches:

```powershell
.\.venv\Scripts\python.exe scripts/generate_batches.py --start-date 2018-01-01 --days 7
```

Verify a batch locally:

```powershell
.\.venv\Scripts\python.exe scripts/upload_batch.py --batch-dir data/local/batches/olist-2018-01-01 --dry-run
```

Upload to the deployed raw bucket:

```powershell
$rawBucket = terraform -chdir=infra output -raw raw_bucket_name

.\.venv\Scripts\python.exe scripts/upload_batch.py --batch-dir data/local/batches/olist-2018-01-01 --bucket $rawBucket
```

## Data Flow

```text
Historical CSVs → Daily batches → Integrity checks → S3 files → Manifest
```

Each uploaded manifest references the exact S3 objects belonging to its batch. Failed attempts may leave unreferenced files; existing published batches are not overwritten.

## Validate a Batch

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_batch --batch-dir data/local/batches/olist-2018-01-01

## Planned Processing

Record validation, quarantine, Parquet transformation, Lambda, Step Functions, DynamoDB batch tracking, Glue Data Catalog, Athena, and CloudWatch monitoring.

## Automated Processing and Batch Tracking

Uploading a raw batch manifest automatically starts processing through Amazon EventBridge and AWS Step Functions.

```mermaid
flowchart TD
    UPLOAD["Upload CSV files, then manifest"] --> RAW["S3 raw bucket"]
    RAW --> RULE["EventBridge: match batch manifest"]
    RULE --> WORKFLOW["Step Functions: normalize and validate input"]
    RULE -->|Delivery failure| DLQ["SQS dead-letter queue"]

    WORKFLOW --> STARTED["DynamoDB: record running"]
    STARTED --> LAMBDA["Lambda: validate, transform, and publish"]

    LAMBDA --> CURATED["S3 curated: Parquet and completion manifest"]
    LAMBDA --> QUARANTINE["S3 quarantine: rejected records and validation report"]

    LAMBDA -->|Successful result| SUCCESS["DynamoDB: complete or already_processed"]
    LAMBDA -->|Caught processing error| FAILURE["DynamoDB: failed"]

    SUCCESS --> DONE["Workflow succeeded"]
    FAILURE --> FAILED["Workflow failed"]
```

### Trigger and Publication

- Only raw batch manifest paths match the trigger:
  `batches/olist-YYYY-MM-DD/manifest.json`.
- CSV files are uploaded before the raw manifest.
- The workflow extracts the batch ID and invokes the existing processing Lambda.
- The curated completion manifest is published after all output artifacts.
- Reprocessing a matching completed batch returns `already_processed`.
- Duplicate notifications may start additional executions; conditional publication protects the committed batch.

### Execution Ledger

DynamoDB stores one record per workflow execution.

| Attribute | Description |
|---|---|
| `batch_id` | Partition key identifying the batch |
| `execution_id` | Sort key containing the execution ARN |
| `status` | `running`, `complete`, `already_processed`, or `failed` |
| `started_at` | Execution start time |
| `finished_at` | Time the outcome was recorded |
| `error` | Failure category, when applicable |

The ledger records processing history. The curated completion manifest remains the authority for published data.

### Failure Handling

- EventBridge retries eligible workflow-start failures and sends undeliverable events to an SQS dead-letter queue.
- The queue retains messages for four days.
- Processing failures after workflow startup are handled by Step Functions and recorded in DynamoDB.
- Stopped or overall timed-out executions may leave a `running` ledger record and require reconciliation.

### Verification

Verified manifest filtering, automatic workflow startup, successful publication, ledger updates, safe replay, and an empty delivery-failure queue after successful delivery.

The source remains a historical Olist snapshot replayed in daily batches; automatic triggering does not make it a live shipment event feed.


## Notes

- Historical replay does not reproduce a live order or carrier feed.
- Follow the source dataset’s license and attribution requirements.
- Keep downloaded data, credentials, virtual environments, and Terraform state out of Git.
- AWS usage may incur charges.