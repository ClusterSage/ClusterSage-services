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
    clusterwatch_metrics_enabled: bool = True
    clusterwatch_metrics_interval_seconds: int = 60
    clusterwatch_remediation_enabled: bool = False
    clusterwatch_remediation_cluster_wide: bool = False
    clusterwatch_remediation_allowed_namespaces: str = ""
    clusterwatch_remediation_allowed_actions: str = "rollout_restart"
    clusterwatch_remediation_poll_interval_seconds: int = 30
    clusterwatch_log_level: str = "info"

    @property
    def remediation_allowed_namespaces(self) -> list[str]:
        return [item.strip() for item in self.clusterwatch_remediation_allowed_namespaces.split(",") if item.strip()]

    @property
    def remediation_allowed_actions(self) -> list[str]:
        return [item.strip() for item in self.clusterwatch_remediation_allowed_actions.split(",") if item.strip()]

settings = Settings()
