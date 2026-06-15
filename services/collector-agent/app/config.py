from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    clusterwatch_backend_url: str
    clusterwatch_email: str
    clusterwatch_access_key: str
    clusterwatch_cluster_name: str
    clusterwatch_cluster_provider: str = "aks"
    clusterwatch_agent_version: str = "0.1.0"
    clusterwatch_heartbeat_interval_seconds: int = 30
    clusterwatch_snapshot_interval_seconds: int = 60
    clusterwatch_log_level: str = "info"

settings = Settings()
