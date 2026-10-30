# CodeHive backend project template

A Python 3.11 / FastAPI starter with dependencies defined in `pyproject.toml`, PR checks,
automated tests, and Heroku deployment. Build your own features around the small
`main.py` application. `/health` is public so deployment can verify that it started.

## Set up and run

1. Use this repository as a GitHub template to create your project, then clone it.
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
3. From the repository root, run:

   ```bash
   uv venv
   uv pip install -r pyproject.toml --group dev
   uv run --no-sync uvicorn main:app --reload
   ```

Open <http://localhost:8000/docs> for Swagger or <http://localhost:8000/health>
for the startup check. Rename the project metadata in `pyproject.toml` for your
project. Add application dependencies to `[project].dependencies` and development
tools to `[dependency-groups].dev`, then rerun
`uv pip install -r pyproject.toml --group dev`. Commit `pyproject.toml` when it changes.
Use `uv run --no-sync` to run tools from the installed environment without creating
a lockfile. Dependency versions are resolved from the declared ranges on installation.

## Check your work locally

```bash
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest --cov --cov-report=term-missing
```

Use `uv run --no-sync ruff format .` to fix formatting. CI installs dependencies
directly from `pyproject.toml`. Tests live in `tests/`; collecting no tests is a failure.
Coverage is reported for review, with no minimum percentage imposed initially.

## Submit a feature for peer review

1. Create a feature branch from an up-to-date `main`.
2. Implement the feature and its tests, then run the local checks.
3. Push the branch and open a **draft PR** using the supplied PR template.
4. Complete the description and testing evidence.
5. Resolve the feedback in GitHub Actions. When the PR gate passes, the bot marks
   the draft ready. Ask a peer to review and approve before merging.

| Workflow | What happens |
|---|---|
| `pr-checks.yml` | PR requirements and lint/format run in parallel. Both must pass before CI is called. A final **PR gate** fails for any failed, cancelled, or skipped required stage. |
| `ci.yml` | A reusable workflow runs pytest and coverage. It is called by PR checks and again before deployment. |
| `deploy.yml` | A push to `main` reruns CI on the merged commit, deploys to Heroku, and checks `/health`. Manual runs are restricted to `main`. |

PR requirements run again when the PR description or labels change, as well as
on new commits. The privileged feedback job never checks out PR code and ignores
results if the PR changed during the run. PRs from forks run all required checks,
but GitHub's read-only fork token prevents bot comments and automatic draft
promotion: mark those PRs ready manually after **PR gate** passes. Peer review
assesses whether the tests are meaningful; changing a test file alone cannot
establish that a feature is well tested.

Exceptions require an explanatory reason of at least 20 characters in the
**Exceptions** section and a matching label applied by a maintainer:

- `no-tests-needed` with `tests: <reason>` for Python changes that need no updated tests.

`N/A` alone is not an exception. The label does not bypass the automated suite.

## Configure merge protection once per student repository

In GitHub repository settings, protect `main` with a branch rule or ruleset:

- Require pull requests and at least **one approving peer review**.
- Require the **PR gate** status check (select it after its first run).
- Require branches to be up to date before merging.
- Dismiss stale approvals when new commits are pushed.
- Disable bypassing the rules, including direct pushes to `main`.

The workflow cannot enforce peer approval without this repository setting.
Enable GitHub Actions. Your organization's policies must allow the feedback job's
`pull-requests: write` permission for automatic draft promotion. No additional
token is needed for ordinary same-repository PRs.

## Configure Heroku deployment

Create the Heroku application first and enable the official Python buildpack.
The deployment workflow generates a runtime-only `requirements.txt` from
`pyproject.toml` for Heroku's Python buildpack. The deploy action includes that file
in its temporary deployment commit; it is not added to your GitHub branch. Development
tools are excluded. `.python-version` selects Python and `Procfile` starts the API
on Heroku's `$PORT`.

Create a GitHub environment named **production** and configure:

| Kind | Name | Value |
|---|---|---|
| Secret | `HEROKU_API_KEY` | Your Heroku API key |
| Secret | `HEROKU_EMAIL` | Your Heroku account email |
| Variable | `HEROKU_APP_NAME` | The existing Heroku app name |
| Variable | `HEROKU_APP_URL` | Its complete public HTTPS URL |

Restrict the production environment to `main`. Set application configuration
such as `DATABASE_URL` and `JWT_SECRET` on Heroku when your features need it;
never put production credentials in source control. CI sets a SQLite database URL
and a test-only JWT key. Your database fixtures must override the application
database dependency when you add database-backed features.

Until the Heroku settings are configured, deployment reports missing configuration
without attempting to create an app. PR checks and local development still work.

The Heroku app must support Git-based deployment (as used by the class project).
For a Heroku generation that requires container deployment, adapt `deploy.yml`
before enabling deployments.
