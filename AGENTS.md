# AGENTS.md - Auto Git History Rewriter

## Build/Test/Lint Commands
- **Install dependencies**: `uv pip install -e .`
- **Run all tests**: `pytest`
- **Run single test**: `pytest tests/test_clustering.py::TestCommitClusterer::test_continuous_commits`
- **Run with coverage**: `pytest --cov=src --cov-report=html`
- **Type checking**: No explicit type checker configured
- **Linting**: No linter configured, follow PEP 8 style

## Code Style Guidelines
- **Imports**: Standard library first, then third-party, then local modules
- **Formatting**: 4-space indentation, max line length ~100 chars
- **Types**: Use type hints for all function parameters and returns
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **Error handling**: Use try/except with specific exceptions, log errors
- **Docstrings**: Google-style docstrings with Args/Returns sections
- **Logging**: Use logging module with descriptive messages
- **File headers**: Chinese module docstrings with purpose description
- **Error messages**: Chinese error messages in user-facing output
- **Constants**: UPPER_CASE for module-level constants