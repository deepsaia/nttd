# nttd

Agent-agnostic OpenTTD as an AI simulation and benchmarking environment.

## When in doubt,
- When in doubt, read `docs/cli_guide.md`
- Lint: `uv run ruff check src/ tests/`

---

# Coding Guidelines & Best Practices

---

## General Principles

* Write **clear, maintainable, and modular code**.
* Prefer **explicitness over cleverness**.
* Keep functions and modules **small and focused**.
* Do not ever write nested functions or classes.
* Avoid duplication; reuse existing utilities where possible.
* Prioritize **readability and maintainability** over premature optimization.

---

## Code Style

* Follow **PEP8** for formatting, naming conventions, and import conventions.
* Organize imports into standard library, third-party, and local modules.
* Use **explicit type hints** for all functions and methods.
* Avoid untyped interfaces unless absolutely necessary.

---

## Module Design

* Each module should have a **single clear responsibility**. And therefore have only a single class per module.
* Avoid excessively large modules or functions.
* Group related functionality logically within packages.
* Do **not place anything logic** inside `__init__.py`.
* Avoid global variables unless absolutely necessary.
* Favor simple, well-understood design patterns when appropriate.

---

## Error Handling & Logging

* Handle exceptions **explicitly and consistently**.
* Do not silently swallow exceptions.
* Provide meaningful error messages and logging.
* Use a structured logging approach instead of `print` statements.
* Ensure logs provide sufficient context for debugging and monitoring.

---

## Testing

* Write tests for new functionality whenever possible.
* Ensure tests cover normal behavior, edge cases, and failure scenarios.
* Tests should be deterministic and easy to run.
