"""Build a Lambda ZIP containing only explicitly selected files."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "lambda_handler.py",
    "src/__init__.py",
    "src/data_validator.py",
    "src/data_transformer.py",
    "src/s3_pipeline.py",
    "src/local_storage.py",
    "scripts/__init__.py",
    "scripts/generate_batches.py",
    "scripts/upload_batch.py",
    "scripts/validate_batch.py",
    "scripts/transform_batch.py",
    "data/sample/olist_orders_dataset.csv",
    "data/sample/olist_order_items_dataset.csv",
]


def main():
    contents = {}

    for relative_path in FILES:
        path = ROOT / relative_path

        if not path.is_file():
            raise FileNotFoundError(
                f"Required package file missing: {relative_path}"
            )

        payload = path.read_bytes()

        if path.suffix == ".py":
            compile(payload, relative_path, "exec")

        contents[relative_path] = payload

    destination = ROOT / "infra" / "build" / "transform.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(destination, "w") as archive:
        for relative_path, payload in contents.items():
            info = ZipInfo(relative_path)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED

            archive.writestr(info, payload)

    print(f"Built: {destination}")
    print(f"Files: {len(contents)}")
    print(f"Size: {destination.stat().st_size} bytes")


if __name__ == "__main__":
    main()