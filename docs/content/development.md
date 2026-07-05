# Development & Contribution

This guide covers how to contribute to Protolink, from setting up your development environment to submitting pull requests.

## Getting Started

### Prerequisites

<div className="provider-strip-label">[ Python ]   [ Git ]   [ uv ]</div>

<div className="provider-strip">
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/python.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/git.svg" width="55" className="hover-icon" />
  <img src="https://raw.githubusercontent.com/pheralb/svgl/42f8f2de1987d83a7c6ad9d5dc2576377aa5110b/static/library/uv.svg" width="55" className="hover-icon" />
</div>

- **Python 3.10+** - Required for all development
- **Git** - For version control
- **uv** - Recommended package manager (or `pip`)

### Clone and Setup

```bash
# Clone the repository
git clone https://github.com/nMaroulis/protolink.git
cd protolink

# Install in development mode
uv pip install -e ".[dev]"
npm install

# Or with pip
pip install -e ".[dev]"
npm install
```

This installs Protolink in editable mode with all development dependencies.

---

## Development Workflow

### 1. Fork and Clone

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:

```bash
git clone https://github.com/<your-username>/protolink.git
cd protolink

# Add upstream for syncing
git remote add upstream https://github.com/nMaroulis/protolink.git
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 3. Make Changes

- Write your code
- Add tests for new functionality
- Update documentation if needed

### 4. Quality Checks

```bash
# Format code
ruff format .

# Lint and auto-fix
ruff check . --fix

# Type checking
ty check protolink

# Run tests
python -m pytest -v tests

# Validate docs
npm run build
```

### 5. Commit and Push

```bash
git add .
git commit -m "feat: add your feature description"
git push origin feature/your-feature-name
```

### 6. Open Pull Request

- Open a PR from your fork to `main`
- Describe your changes clearly
- Include any breaking changes

---

## Code Quality

### Formatting and Linting

Protolink uses **Ruff** for code formatting and linting.

:::info[Ruff Configuration]

The project uses the default Ruff configuration with some custom rules. See `ruff.toml` for details.

:::
```bash
# Format all code
ruff format .

# Lint and auto-fix issues
ruff check . --fix

# Check without auto-fixing
ruff check .
```

### Type Checking

Protolink uses **ty** for static type checking.

```bash
# Run type checks
ty check protolink

# Check one package area
ty check protolink/agents
```

:::tip[Type Safety]

- All new code should be fully typed
- Use `str | None` instead of `Optional[str]` (PEP 604)
- Add type hints for all public APIs

:::
### Testing

Run the test suite with pytest:

```bash
# Run all tests
python -m pytest -v tests

# Run specific test file
python -m pytest -v tests/test_agent.py

# Run with coverage
python -m pytest --cov=protolink tests
```

:::info[Test Structure]

- Unit tests: `tests/test_*.py`
- Integration tests: `tests/integration/`
- Fixtures and utilities in `tests/conftest.py`

:::
---

## Development Tools

### Pre-commit Hooks

The project includes pre-commit hooks for code quality:

```bash
# Install pre-commit hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

### Documentation

Preview documentation locally:

```bash
cd docs

# Serve docs
npm run start

# Validate docs
npm run build

# Open http://localhost:3000/protolink/
```

Deploy documentation (maintainers only):

```bash
cd docs
npm run build
```

Pull requests run `npm run build` from `docs/`. Pushes to `main` that touch docs, the README, Docusaurus configuration, or docs dependencies upload `docs/build` as a GitHub Pages artifact and deploy it through the `github-pages` environment.

---

## Project Structure

```
protolink/
├── protolink/           # Main package
│   ├── agents/         # Agent implementations
│   ├── client/         # Client code
│   ├── core/           # Core models
│   ├── discovery/      # Registry and discovery
│   ├── llms/           # LLM integrations, infer loop, parsing, and metrics
│   ├── models/         # Exposes core models for importation
│   ├── server/         # Server implementations
│   ├── transport/      # Transport layers
│   ├── tools/          # Tools and adapters (e.g. MCP)
│   ├── types/          # Type aliases
│   └── utils/          # Utilities
├── tests/              # Test suite
├── docs/               # Documentation
├── examples/           # Example scripts
└── README.md          # Project overview
```

---

## Contribution Guidelines

### Code Style

- Follow PEP 8 and PEP 604
- Use descriptive variable and function names
- Add docstrings for all public functions and classes
- Keep functions focused and single-purpose

### Commit Messages

Use conventional commits:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `style:` - Code style changes
- `refactor:` - Code refactoring
- `test:` - Test changes
- `chore:` - Maintenance tasks

### Pull Request Process

1. **Update Documentation** - If your change affects user-facing APIs
2. **Add Tests** - Ensure new functionality is covered
3. **Pass CI** - All checks must pass
4. **Review** - Address feedback from maintainers

:::warning[Breaking Changes]

If your change includes breaking changes:
- Clearly document them in the PR
- Update the version in `__version__.py`
- Add migration notes to documentation

:::
---

## Debugging and Troubleshooting

### Common Issues

#### Type Checking Errors

```bash
# Check specific file for detailed errors
ty check protolink/your/file.py --verbose
```

#### Test Failures

```bash
# Run tests with detailed output
pytest -v -s tests/test_failing.py

# Run specific test with debugging
pytest -v -s tests/test_failing.py::test_function
```

#### Import Issues

```bash
# Install in development mode
python -m pip install -e .

# Check Python path
python -c "import protolink; print(protolink.__file__)"
```

### Development Tips

- Use `uv` for faster dependency management
- Enable debug logging: `export PROTOLINK_LOG_LEVEL=debug`
- Use breakpoints: `import pdb; pdb.set_trace()`
- For watch-mode testing, install a watcher such as `pytest-watch` locally and run it outside the core dependency set.

---

## Release Process

Maintainers can follow this process for releases:

1. **Update Version** in `protolink/__version__.py`
2. **Update Changelog** in `docs/changelog.md`
3. **Tag Release**: `git tag vX.Y.Z`
4. **Push Tags**: `git push origin --tags`
5. **Build Package**: `python -m build`
6. **Upload to PyPI**: `python -m twine upload dist/*`

---

## Community

### Getting Help

- **GitHub Issues** - Bug reports and feature requests
- **Discussions** - General questions and ideas
- **Documentation** - API reference and guides

### Code of Conduct

Please be respectful and constructive in all interactions. By participating in this project, you agree to follow our community guidelines.

---

Thank you for contributing to Protolink.
