# Contributing to YouTube Summary Notify

Thank you for your interest in contributing! This guide will help you get started.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/sohei56/youtube-summary-notify-with-gemini/issues) using the **Bug Report** template. Include:

- Steps to reproduce
- Expected vs actual behavior
- Python version, AWS region, and OS

## Requesting Features

Open a [GitHub Issue](https://github.com/sohei56/youtube-summary-notify-with-gemini/issues) using the **Feature Request** template.

## Development Setup

```bash
git clone git@github.com:sohei56/youtube-summary-notify-with-gemini.git
cd youtube-summary-notify-with-gemini
pip install -e ".[dev]"
```

## Code Style

This project uses **ruff** for formatting and linting. See [docs/01_design/03_coding-standards.md](docs/01_design/03_coding-standards.md) for the full coding standards.

Key points:

- Type hints on all function signatures
- Docstrings on public functions and classes (Google style)
- `ruff format .` to format code
- `ruff check .` to lint code

## Testing

All tests must pass before submitting a PR.

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# E2E tests only
pytest tests/e2e/ -v
```

## Pull Request Workflow

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes
4. Ensure tests pass and linting is clean
5. Submit a Pull Request against `main`
