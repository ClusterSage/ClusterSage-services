import gzip
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContentSettings
from app.core.config import settings

class BlobWriter:
    def __init__(self) -> None:
        if not settings.azure_storage_connection_string:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
        self.client = BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)
        self.container_name = settings.azure_storage_container

    def _prefix(self, kind: str, org_id: str, cluster_id: str, filename_prefix: str) -> str:
        now = datetime.now(timezone.utc)
        return f"{kind}/orgId={org_id}/clusterId={cluster_id}/year={now:%Y}/month={now:%m}/day={now:%d}/hour={now:%H}/{filename_prefix}_{uuid.uuid4()}.json.gz"

    def upload_json_gz(self, kind: str, org_id: str, cluster_id: str, filename_prefix: str, payload: Any) -> tuple[str, int]:
        container = self.client.get_container_client(self.container_name)
        try:
            container.create_container()
        except ResourceExistsError:
            pass
        blob_path = self._prefix(kind, org_id, cluster_id, filename_prefix)
        raw = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
        body = gzip.compress(raw)
        container.upload_blob(blob_path, body, overwrite=False, content_settings=ContentSettings(content_type="application/json", content_encoding="gzip"))
        return blob_path, len(body)

class BlobReader:
    def __init__(self) -> None:
        if not settings.azure_storage_connection_string:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
        self.client = BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)
        self.container_name = settings.azure_storage_container

    def read_json_gz(self, blob_path: str) -> Any:
        if ".." in blob_path or blob_path.startswith("/") or "\\" in blob_path:
            raise ValueError("Invalid blob path")
        container = self.client.get_container_client(self.container_name)
        body = container.download_blob(blob_path).readall()
        try:
            raw = gzip.decompress(body)
        except gzip.BadGzipFile:
            raw = body
        return json.loads(raw.decode("utf-8"))
