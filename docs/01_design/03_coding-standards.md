# Coding Standards

## Language & Runtime

- Python 3.12+
- Async-first: use `async/await` for all I/O operations
- Async HTTP: `httpx.AsyncClient`

## Dependencies

Core dependencies:

- `google-genai` — Gemini API SDK
- `httpx` — async HTTP client (YouTube API, Slack Webhooks)
- `boto3` — AWS SDK (S3, DynamoDB, Secrets Manager)
- `pyyaml` — config.yaml parsing

Testing:

- `pytest` + `pytest-asyncio`
- `moto` — AWS service mocking

All versions pinned in `pyproject.toml`. Minimize third-party dependencies.

## Formatting & Linting

- Formatter: `ruff format`
- Linter: `ruff check`
- Configuration in `pyproject.toml`

## Code Style

- Type hints on all function signatures
- Docstrings on public functions and classes (Google style)
- No wildcard imports
- Prefer explicit over implicit

## Naming Conventions

- Modules: `snake_case.py`
- Classes: `PascalCase`
- Functions / variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

## Error Handling

- Never silently swallow exceptions
- Log all exceptions with traceback at ERROR level
- Use specific exception types, not bare `except`

## Testing

- Framework: pytest + pytest-asyncio
- Test files: `tests/test_<module>.py`
- Use fixtures for shared setup (S3, DynamoDB mocks via `moto`)
- Mock external APIs (YouTube, Gemini, Slack) — no real API calls in tests

## Containerization

- Base image: AWS Lambda Python base image
- Dockerfile at project root
- Docker is required for `sam build` (Lambda container image)
