# Contributing to BusinessIntelligence.ai

Thanks for considering a contribution. This project is a three-person team effort, and
clear, reviewable contributions keep it healthy.

Please read this guide before opening a pull request.

---

## 1. Code of Conduct

All contributors must follow our [Code of Conduct](.github/CODE_OF_CONDUCT.md).
Be respectful, constructive, and evidence-based in discussions — exactly how the
system itself behaves.

## 2. Before you start

- Read the [README](README.md) to understand the design philosophy
  ("the analytical layer determines the truth; the LLM explains that truth").
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) to see where a change would fit.
- Check open issues and existing pull requests to avoid duplicated work.

## 3. Reporting issues

Use the provided issue templates:

- [Bug report](.github/ISSUE_TEMPLATE/bug_report.yml)
- [Feature request](.github/ISSUE_TEMPLATE/feature_request.yml)

A good bug report includes the exact command run, the observed output, the expected
output, and the environment (Python version, OS).

## 4. Development setup

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Optional but recommended for sentiment work:

```powershell
python -m pip install sentencepiece protobuf
```

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for a full walkthrough.

## 5. Making changes

### Branch naming

```text
feat/<short-description>
fix/<short-description>
docs/<short-description>
refactor/<short-description>
```

### Commit messages

Use conventional commit style:

```text
feat: add segment contribution breakdown by category
fix: handle NaN values in analytical API responses
docs: explain sparse-history abstention behavior
```

### Pull request checklist

- [ ] Branch is based on the latest `main`
- [ ] Change is scoped — one logical change per PR
- [ ] No secrets are committed (check for API keys)
- [ ] `python run_pipeline.py` still runs (or a targeted module still runs)
- [ ] Relevant validation modules pass: `scenarios/scenario_runner.py`,
      `scenarios/sparse_history.py`
- [ ] README is updated if user-facing behavior changed

## 6. Design guardrails

When proposing changes, respect these invariants:

1. **Deterministic-first**: analytical values must never depend on an LLM.
2. **Contribution is not causality**: keep evidence types explicit.
3. **Abstention is a feature**: adding confidence/evidence checks is welcome,
   weakening them needs strong justification.
4. **Inspectability**: new artifacts should be written as JSON under `data/`.
5. **No secrets**: API keys only via environment variables / local `.env`.

## 7. Documentation contributions

Docs are first-class contributions:

- User-facing guides live in `docs/`.
- The page-level overview lives in `README.md`.
- Credit files: `AUTHORS.md` and `CHANGELOG.md` are maintained by the team.

Please keep documentation accurate to the current behavior of the code.

## 8. Review process

Every pull request should get at least one approving review before merge. The project
maintainers are listed in [AUTHORS.md](AUTHORS.md).