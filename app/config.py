from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8400

    # Documentation-only REST/Swagger facade over the same seven tools (see app/rest_api.py).
    # agent-runtime-renegotiation talks to this service over MCP (mcp_port), never over this port.
    docs_port: int = 8401

    renegotiation_service_base_url: str = "http://localhost:9400"
    renegotiation_service_retry_attempts: int = 2

    # 9092 is Kafka's PLAINTEXT listener, advertised as "kafka:9092" (only resolvable inside
    # the Docker network); 29092 is the EXTERNAL listener, advertised as "localhost:29092",
    # for this service running on the host (e.g. via `python -m app.main` outside Docker).
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_tool_events_topic: str = "tool.executed"


def get_settings() -> Settings:
    return Settings()
