from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8400
    docs_port: int = 8401

    renegotiation_service_base_url: str = "http://localhost:9400"
    renegotiation_service_audience: str = "renegotiation-service"
    renegotiation_service_retry_attempts: int = 2

    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_tool_events_topic: str = "tool.executed"
    otel_otlp_endpoint: str = "http://localhost:4317"

    internal_auth_enabled: bool = True
    internal_auth_issuer: str = "conversational-ai-platform"
    internal_auth_service_name: str = "tool-service-renegotiation"
    internal_auth_signing_key: str = ""
    internal_auth_token_ttl_seconds: int = 300


def get_settings() -> Settings:
    return Settings()
