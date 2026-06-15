from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_env: str = "development"
    app_name: str = "ClusterSage"
    public_app_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    database_url: str = "postgresql+asyncpg://clusterwatch:clusterwatch@localhost:5432/clusterwatch"
    jwt_secret: str = Field(default="dev-only-change-me", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    agent_token_secret: str = Field(default="dev-only-agent-secret", min_length=16)
    agent_token_expire_hours: int = 720
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "clusterwatch-data"
    azure_servicebus_connection_string: str = ""
    azure_servicebus_fully_qualified_namespace: str = ""
    cluster_connected_queue_name: str = "cluster-connected"
    azure_communication_email_connection_string: str = ""
    azure_communication_email_endpoint: str = ""
    email_sender_address: str = ""
    email_worker_poll_seconds: int = 10
    log_batch_max_size_mb: int = 10
    log_retention_days: int = 30
    cors_allowed_origins: str = "http://localhost:3000"
    ai_provider: str = "disabled"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

settings = Settings()
