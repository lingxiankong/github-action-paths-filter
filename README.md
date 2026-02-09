# Python Paths Filter

This action is a Python implementation of [dorny/paths-filter](https://github.com/dorny/paths-filter). It allows you to conditionally run actions based on files modified by PRs, feature branches, or pushed commits.

## Why this fork?

This version is implemented in Python to support environments where Node.js actions or external dependencies (like those required by `dorny/paths-filter`) might be restricted or unavailable (e.g., air-gapped enterprise environments). It mimics the core functionality of the original action.

## Usage

### Basic Example

```yaml
- uses: ./path/to/action  # or lingxiankong/github-action-paths-filter@main
  id: filter
  with:
    filters: |
      src:
        - 'src/**'
      docs:
        - 'docs/**'

- name: Tests
  if: steps.filter.outputs.src == 'true'
  run: pytest

- name: Build Docs
  if: steps.filter.outputs.docs == 'true'
  run: make html
```

### Inputs

| Input | Description | Required | Default |
| --- | --- | --- | --- |
| `filters` | Path patterns to match against changed files. YAML format (or JSON). | **Yes** | |
| `base` | Git reference (branch name) used as a base for diff. | No | |
| `ref` | Git reference (branch name) used as a head for diff. | No | |
| `working-directory` | Relative path under `$GITHUB_WORKSPACE` where the repository was checked out. | No | `.` |
| `list-files` | Enables listing of files matching the filter: `none`, `csv`, `json`, `shell`, `escape`. | No | `none` |

### Outputs

- **`changes`**: JSON array with names of all filters matching any of changed files.
- **`<filter-name>`**: `true` if any of changed files matches the filter rules, `false` otherwise.
- **`<filter-name>_count`**: Count of matching files.
- **`<filter-name>_files`**: List of matching files (format depends on `list-files` input).

## Implementation Details

- **Language**: Python 3
- **Dependencies**:
  - `PyYAML` (optional but recommended for YAML filter parsing).
  - Standard library (`subprocess`, `json`, `re`, `shlex`) used for core logic.
- **Git Logic**: Uses `git diff` and `git merge-base` to detect changes.
- **Glob Matching**: Supports standard glob patterns:
  - `*`: Matches any character except path separator.
  - `**`: Matches any character including path separator (recursive).
  - `?`: Matches single character.

## Air-Gapped / No-Internet Usage

If your environment cannot install `PyYAML` at runtime (`pip install` fails), you have two options:
1. Ensure `PyYAML` is pre-installed in your runner image.
2. Provide `filters` input as a **JSON string** instead of YAML. The action handles JSON natively without extra dependencies.

```yaml
- uses: ./path/to/action
  with:
    # filters as JSON string
    filters: '{"src": ["src/**"], "docs": ["docs/**"]}'
```
