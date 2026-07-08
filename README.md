# Tool Service Renegotiation

Serviço MCP responsável por expor ferramentas governadas de renegociação de dívidas para o `agent-runtime-renegotiation`.

Este serviço encapsula chamadas ao serviço core de renegociação, publica eventos de execução de tools no Kafka e evita expor diretamente integrações sensíveis ao agente.

## Visão geral

```mermaid
flowchart LR
    AgentRuntime[Agent Runtime Renegotiation] -->|MCP streamable-http| ToolService[Tool Service Renegotiation]
    ToolService -->|HTTP REST| RenegotiationService[Renegotiation Service]
    ToolService -->|tool.executed| Kafka[(Kafka)]
```

## Stack

- Python 3.9+
- MCP / FastMCP
- HTTPX
- Tenacity
- Confluent Kafka
- Pydantic Settings
- Uvicorn
- Pytest

## Responsabilidades

- Expor tools MCP para o runtime do agente.
- Encapsular chamadas HTTP ao serviço core de renegociação.
- Aplicar retry nas chamadas ao serviço de renegociação.
- Instrumentar toda execução de tool com evento Kafka.
- Não registrar argumentos sensíveis, como CPF e identificadores de contrato, no payload de auditoria.
- Manter o agente desacoplado das APIs internas de renegociação.

## Tools MCP

O serviço registra 7 tools MCP governadas.

| Tool | Entrada | Descrição | Endpoint chamado |
|---|---|---|---|
| `consultar_cliente` | `cpf: str` | Consulta dados cadastrais do cliente pelo CPF. | `GET /clients/{cpf}` |
| `consultar_contratos` | `client_id: str` | Consulta contratos de um cliente. | `GET /clients/{client_id}/contracts` |
| `consultar_debitos` | `contract_id: str` | Consulta débitos em aberto de um contrato. | `GET /contracts/{contract_id}/debts` |
| `validar_elegibilidade` | `contract_id: str` | Valida elegibilidade de um contrato para renegociação. | `GET /contracts/{contract_id}/eligibility` |
| `simular_proposta` | `contract_id: str`, `installments: int`, `discount_percentage: float = 0.0` | Simula proposta de renegociação. | `POST /contracts/{contract_id}/simulations` |
| `confirmar_acordo` | `simulation_id: str` | Confirma e formaliza acordo a partir de uma simulação. | `POST /simulations/{simulation_id}/confirmations` |
| `gerar_documento` | `agreement_id: str` | Gera documento ou comprovante de acordo formalizado. | `GET /agreements/{agreement_id}/document` |

## Contratos de exemplo

### `consultar_cliente`

```json
{
  "cpf": "12345678900"
}
```

### `consultar_contratos`

```json
{
  "client_id": "client-001"
}
```

### `consultar_debitos`

```json
{
  "contract_id": "contract-001"
}
```

### `validar_elegibilidade`

```json
{
  "contract_id": "contract-001"
}
```

### `simular_proposta`

```json
{
  "contract_id": "contract-001",
  "installments": 12,
  "discount_percentage": 15.0
}
```

### `confirmar_acordo`

```json
{
  "simulation_id": "simulation-001"
}
```

### `gerar_documento`

```json
{
  "agreement_id": "agreement-001"
}
```

## Evento Kafka

Toda execução de tool publica um evento no tópico configurado.

### Tópico: `tool.executed`

```json
{
  "tool_name": "consultar_cliente",
  "outcome": "success",
  "correlation_id": "b4f4d4c2f7d94ef0a8e4d8d6f7c2a123"
}
```

### Observações

- `outcome` pode ser `success` ou `error`.
- O evento é publicado tanto em sucesso quanto em falha.
- O payload não inclui argumentos da tool para evitar vazamento de CPF, contratos ou identificadores sensíveis.
- Falhas na publicação Kafka são registradas em log, mas não interrompem a execução da tool.

## Configuração

O serviço usa `pydantic-settings` com variáveis de ambiente.

| Variável | Default | Descrição |
|---|---:|---|
| `MCP_HOST` | `0.0.0.0` | Host onde o servidor MCP será exposto. |
| `MCP_PORT` | `8400` | Porta do servidor MCP. |
| `DOCS_PORT` | `8401` | Porta da fachada REST/Swagger somente para documentação (ver seção abaixo). |
| `RENEGOTIATION_SERVICE_BASE_URL` | `http://localhost:9400` | Base URL do serviço core de renegociação. |
| `RENEGOTIATION_SERVICE_RETRY_ATTEMPTS` | `2` | Tentativas adicionais em chamadas ao serviço de renegociação. |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Bootstrap servers do Kafka. |
| `KAFKA_TOOL_EVENTS_TOPIC` | `tool.executed` | Tópico de eventos de execução de tools. |

Exemplo:

```bash
export MCP_HOST="0.0.0.0"
export MCP_PORT="8400"
export RENEGOTIATION_SERVICE_BASE_URL="http://localhost:9400"
export KAFKA_BOOTSTRAP_SERVERS="localhost:9092"
export KAFKA_TOOL_EVENTS_TOPIC="tool.executed"
```

## Como executar localmente

### Pré-requisitos

- Python 3.9+
- Kafka local em `localhost:9092`
- Serviço core de renegociação disponível em `localhost:9400`
- Cliente MCP, como o `agent-runtime-renegotiation`, apontando para `http://localhost:8400/mcp`

### Criar ambiente virtual

```bash
python -m venv .venv
```

Ativar no Windows:

```bash
.venv\Scripts\activate
```

Ativar no Linux/macOS:

```bash
source .venv/bin/activate
```

### Instalar dependências

```bash
pip install -r requirements.txt
```

Para desenvolvimento e testes:

```bash
pip install -r requirements-dev.txt
```

### Subir servidor MCP

```bash
python -m app.main
```

O servidor sobe em:

```text
http://localhost:8400/mcp
```

O mesmo processo também sobe, na porta `DOCS_PORT` (default `8401`), uma **fachada REST somente para documentação** (`app/rest_api.py`) espelhando as mesmas 7 tools via Swagger UI:

```text
http://localhost:8401/docs
```

MCP não tem uma superfície OpenAPI própria — é um protocolo JSON-RPC-like sobre streamable-HTTP, não REST. Essa fachada existe só para permitir explorar/testar as tools com uma UI; nenhum cliente do workspace a consome (`agent-runtime-renegotiation` fala MCP em `:8400/mcp`, não REST).

## Testes

```bash
pytest
```

O `pyproject.toml` aponta os testes para a pasta `tests` e usa `asyncio_mode = auto`.

## Estrutura

```text
.
├── app
│   ├── events
│   │   ├── instrumentation.py
│   │   └── publisher.py
│   ├── config.py
│   ├── logging_setup.py
│   ├── main.py
│   ├── mcp_server.py
│   └── renegotiation_client.py
├── tests
│   ├── test_mcp_server_integration.py
│   ├── test_publisher.py
│   ├── test_renegotiation_client.py
│   └── test_tools.py
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── tool-service-renegotiation.pyproj
```

## Integrações

### Agent Runtime Renegotiation

Consome as tools expostas via MCP em `http://localhost:8400/mcp`.

### Renegotiation Service

Serviço HTTP core que fornece dados de cliente, contratos, débitos, elegibilidade, simulações, confirmações e documentos.

### Kafka

Recebe eventos `tool.executed` para observabilidade e auditoria de execução das tools.

## Resiliência e segurança

- Chamadas ao serviço core usam retry com espera fixa curta.
- Quando as tentativas esgotam, o client lança `RenegotiationServiceUnavailableError`.
- Logs evitam imprimir URLs de erro, pois podem conter CPF ou identificadores sensíveis.
- Eventos Kafka não carregam argumentos das tools.
- Cada execução recebe um `correlation_id` gerado internamente.

## Próximos passos sugeridos

- Adicionar Dockerfile e docker-compose local.
- Documentar contrato do serviço core de renegociação.
- Criar mocks locais para os endpoints `/clients`, `/contracts`, `/simulations` e `/agreements`.
- Adicionar health check para Kafka e Renegotiation Service.
- Adicionar pipeline CI com testes e análise estática.
