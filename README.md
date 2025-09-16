[![CI](https://github.com/meeghele/au-revoir-gitlab/actions/workflows/ci.yml/badge.svg)](https://github.com/meeghele/au-revoir-gitlab/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

# Au Revoir GitLab

A Python command-line tool that syncs/migrates all repositories from a GitLab namespace into a GitHub organization using git clone and push.

<div align="center">
  <img src="images/au-revoir-gitlab_512.png" alt="Au Revoir GitLab Logo" width="200"/>
</div>

## Features

- **Namespace discovery**: Finds all projects under a GitLab namespace, including nested subgroups
- **Org import**: Creates repositories in the target GitHub organization (privacy preserved; internal → private)
- **Git-based import**: Uses git clone/push to import all refs and history (replaces deprecated GitHub Import API)
- **Dry run**: Preview actions without doing them
- **Filters**: Exclusion pattern and archived projects toggle
- **Collision-safe naming**: Automatic name collision handling with stable suffixes
- **Re-import option**: Force re-import by deleting pre-existing repos
- **Progress waiting**: Optional wait for import completion

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
python au-revoir-gitlab.py [options]
```

### Authentication

Set tokens via env vars (recommended) or flags:

- `GITLAB_TOKEN` or `--gl-token`
- `GITHUB_TOKEN` or `--gh-token`
- `GITLAB_USERNAME` or `--gl-username` (required for private repos)

Example:

```bash
export GITLAB_TOKEN=glpat_xxx
export GITHUB_TOKEN=ghp_xxx
export GITLAB_USERNAME=your_gitlab_username
python au-revoir-gitlab.py --gl-namespace preava --gh-org preava
```

### Command Line Options

| Option | Long Option | Description |
|--------|-------------|-------------|
|  | `--gl-url` | Base URL of the GitLab instance (default: `https://gitlab.com`) |
|  | `--gl-token` | GitLab API token (or set `GITLAB_TOKEN` env var) |
|  | `--gl-namespace` | GitLab root namespace (group) to sync |
|  | `--gl-username` | GitLab username for HTTPS git auth (required for private repos) |
|  | `--gh-api` | Base URL of the GitHub API (default: `https://api.github.com`) |
|  | `--gh-token` | GitHub API token (or set `GITHUB_TOKEN` env var) |
|  | `--gh-org` | GitHub organization to import into |
| `-d` | `--dry-run` | List actions without doing them |
| `-e` | `--exclude` | Pattern to exclude from subgroups and projects |
|  | `--include-archived` | Include archived GitLab projects |
|  | `--force-reimport` | Delete existing GitHub repo if present and re-import |
|  | `--no-wait` | Skip GitHub availability pre-check before pushing |
|  | `--name-prefix` | Optional prefix to add to every GitHub repo name |
|  | `--flatten-sep` | Separator used when flattening subgroup path (default: `-`) |
|  | `--visibility` | Visibility for created GitHub repos: `private` (default) or `public` |
|  | `--retry-delay` | Seconds to wait between retry attempts (default: `3.0`) |
|  | `--clone-temp-dir` | Temporary directory for git clones (default: `/tmp/au-revoir-gitlab`) |
|  | `--clone-method` | Clone method for GitLab source: `https` (default) or `ssh` |
|  | `--push-method` | Push method for GitHub target: `https` (default) or `ssh` |

### Naming

- Default flattening uses `-` between subgroup segments.
  - Example: `preava/a/b/c/d/e` → `a-b-c-d-e` in GitHub.
- You can change the separator with `--flatten-sep`.
  - Example: `--flatten-sep _` → `a_b_c_d_e`.
- Use `--name-prefix` to add a prefix; it uses the same separator.
  - Example: `--name-prefix gl --flatten-sep _` → `gl_a_b_c_d_e`.

#### Collision handling
- If two GitLab projects map to the same GitHub name (after flattening/sanitizing), a stable suffix is added based on the GitLab project ID, e.g. `repo` → `repo_gl12345`.
- If a repo with that name already exists in the GitHub org and `--force-reimport` is NOT used, the tool appends `_gl<ID>` and, if needed, `_gl<ID>_2`, etc.
- If `--force-reimport` is used and a repo already exists with the planned name, it is deleted and recreated before import.

## Examples

**Dry run:**
```bash
python au-revoir-gitlab.py --gl-namespace preava --gh-org preava --dry-run
```

**Real sync:**
```bash
python au-revoir-gitlab.py --gl-namespace preava --gh-org preava
```

**Avoid name clashes with a prefix:**
```bash
python au-revoir-gitlab.py --gl-namespace preava --gh-org preava --name-prefix gl
```

**Using SSH for both clone and push:**
```bash
python au-revoir-gitlab.py --gl-namespace preava --gh-org preava --clone-method ssh --push-method ssh
```

## Exit Codes

| Code | Description |
|------|-------------|
| 0 | Success |
| 1 | Execution error |
| 2 | Missing required arguments |
| 30 | GitLab API error |
| 31 | GitHub API error |
| 40 | Authentication error |

## Preflight checks

On startup, the tool performs a preflight against the target GitHub organization:

- Checks the organization exists/is visible (`GET /orgs/{org}`):
  - 401 Unauthorized: token invalid or not authorized for the API.
  - 403 Forbidden: token lacks permission to access the org (missing `read:org`, fine‑grained token not granted to the org, or SAML SSO not authorized).
  - 404 Not Found: org does not exist or is private and not visible to this token (not a member).
  - Any of these conditions will stop execution with a clear message.
- Attempts to check membership (`GET /user/memberships/orgs/{org}`):
  - Logs your membership `state` (active/pending) and `role` (admin/member) when possible.
  - If membership isn’t active, the tool aborts.
  - If role isn’t admin, it warns repo creation may be restricted by org settings.
  - If scopes block this check: 
    - 401 Unauthorized: token not authorized to read memberships.
    - 403 Forbidden: missing `read:org`, fine‑grained token not granted to org, or SAML SSO not authorized.
    - 404 Not Found: not a member or org is private and not visible.
    - In these cases it warns and proceeds.

## Import Method (Updated 2024)

**Important Note**: As of April 2024, GitHub has deprecated and shut down the Source Import REST API endpoints. This tool now uses a git-based approach for importing repositories.

### Current Import Process

1. **Repository Creation**: Creates the target repository on GitHub using the GitHub API
2. **Local Clone**: Clones the source GitLab repository to a temporary directory (`--clone-temp-dir`)
3. **Mirror Push**: Pushes all refs and history from the local clone to GitHub using `git push --mirror`
4. **Cleanup**: Automatically removes the temporary clone directory

### Temporary Directory Management

- The tool creates temporary directories under `--clone-temp-dir` (default: `/tmp/au-revoir-gitlab`)
- Each repository gets its own subdirectory with a unique name
- All temporary directories are automatically cleaned up after import completion or failure
- Ensure sufficient disk space is available for the repositories being migrated

### Retry Behavior

- The tool verifies repository accessibility before attempting import
- You can adjust retry timing with `--retry-delay` (default 3s)
- For private/internal GitLab projects, you must supply `--gl-username` (or `GITLAB_USERNAME`) along with `GITLAB_TOKEN` for authentication

### Why the Change?

GitHub deprecated the Source Import REST API on April 12, 2024, citing low usage and the availability of better alternatives. The git-based approach provides:
- Better error handling and reliability
- Direct control over the import process
- Support for all Git features and edge cases

## Token Permissions

- GitLab: API scope and permission to read the source group projects. For HTTPS git auth, the PAT must allow repository read access; use your GitLab username with the PAT as password.
- GitHub: Access to create repositories in the target organization. Repository creation and git push access are required.

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome, please follow the semantic versioning branch naming convention:

- **main**: Production-ready code
- **develop**: Integration branch for features
- **feat/**: New features (`feat/user-authentication`)
- **fix/**: Bug fixes (`fix/connection-timeout`)
- **chore/**: Maintenance (`chore/update-dependencies`)
