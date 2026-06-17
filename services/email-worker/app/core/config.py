from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "ClusterSage Email Worker"
    azure_servicebus_connection_string: str = ""
    azure_servicebus_fully_qualified_namespace: str = ""
    cluster_connected_queue_name: str = "cluster-connected"
    azure_communication_email_connection_string: str = ""
    azure_communication_email_endpoint: str = ""
    email_sender_address: str = Field(default="")
    email_worker_poll_seconds: int = 10


settings = Settings()
