# Contributing to Protolink

First off, thank you for your interest in contributing to Protolink!

This document describes how to set up a development environment, coding standards, and the preferred contribution workflow.

---

## Getting Started

### Prerequisites

- Python 3.10+ (as advertised in the project badges)
- [uv](https://github.com/astral-sh/uv) **recommended** or `pip`
- Git

### Clone the repository

```bash
git clone https://github.com/nMaroulis/protolink.git
cd protolink
```

### Install dependencies

For development (includes optional deps and tooling):

```bash
# Using uv (recommended)
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

This will install the library in editable mode along with the development extras defined in `pyproject.toml`.

---

## Development Workflow

The preferred way to contribute is via the standard GitHub fork-and-pull-request workflow.

1. **Fork the repository** on GitHub

   - Go to the main Protolink repository.
   - Click **Fork** to create your own copy under your GitHub account.

2. **Clone your fork** locally

   ```bash
   git clone https://github.com/<your-username>/protolink.git
   cd protolink
   ```

   Optionally, add the original repo as `upstream` so you can sync later:

   ```bash
   git remote add upstream https://github.com/nMaroulis/protolink.git
   ```

3. **Create a feature branch** for your change

   ```bash
   git checkout -b feature/my-change
   ```

4. **Make your changes** in the codebase and/or documentation.

5. **Run formatting and linting**:

   ```bash
   # Format code
   ruff format .

   # Lint and auto-fix
   ruff check . --fix
   ```

6. **Run the test suite**:

   ```bash
   pytest
   ```

7. (Optional) **Preview documentation changes**:

   ```bash
   mkdocs serve
   # open http://127.0.0.1:8000
   ```

8. **Commit with a clear message** and push to *your fork*:

   ```bash
   git add .
   git commit -m "Short, descriptive message"
   git push origin feature/my-change
   ```

9. **Open a Pull Request** from your fork to `main` on the upstream repository and briefly describe:

   - What change you are making
   - Why it is needed
   - Any breaking changes or migration steps

---

## Code Style

Protolink uses **Ruff** for linting and formatting.

- Prefer running `ruff format .` before committing.
- Use `ruff check . --fix` to automatically address common issues.
- Keep functions and modules focused and small where it makes sense.

If `ruff` reports issues you are unsure how to fix, feel free to ask in the Pull Request.

---

## Tests

- All new features should include tests when possible.
- Bug fixes should include a regression test demonstrating the issue.
- Existing tests must pass before a PR is merged.

Run tests with:

```bash
pytest
```

If your change requires additional test fixtures or helper utilities, place them in the appropriate `tests/` module.

---

## Documentation

- User-facing changes should be reflected in the docs under `docs/`.
- The README should stay focused on a high-level overview and quick start.
- Detailed guides and reference material belong in the MkDocs documentation.

To build/preview the docs locally:

```bash
mkdocs serve
```

To deploy (for maintainers):

```bash
mkdocs gh-deploy
```

---

## Reporting Issues & Feature Requests

If you encounter a bug or have an idea for an enhancement:

1. Search existing issues to avoid duplicates.
2. Open a new issue with:
   - Clear description of the problem or feature
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (Python version, OS, etc.)

---

## Code of Conduct

Please be respectful and constructive in all interactions.

By participating in this project you agree to follow our community guidelines and to keep discussions inclusive and professional.

---

Thank you again for contributing to Protolink!
