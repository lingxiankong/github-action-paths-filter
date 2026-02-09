import os
import sys
import subprocess
import json
import re
import shlex

def debug(msg):
    """Print a debug message to GitHub Actions log."""
    print(f"::debug::{msg}")

def set_output(name, value):
    """Set a GitHub Action output variable."""
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{name}={value}\n")
    else:
        # Fallback for local testing
        print(f"::set-output name={name}::{value}")

def run_command(command, cwd=None):
    """Run a shell command and return its stdout, raising an error on failure."""
    debug(f"Running command: {command}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        debug(f"Command failed: {e.stderr}")
        raise

def get_commits(base, ref, cwd):
    """
    Get the list of changed files between base and ref.
    Attempts to find a merge-base first to correctly identify changes on the branch.
    Falls back to direct diff if merge-base calculation fails.
    """
    # If base is not provided, we might be in a push event or generic context
    # But usually base is required for PRs.

    # 1. Resolve merge-base if needed
    if base and ref:
        debug(f"Resolving merge-base between {base} and {ref}")
        try:
            # Fetch if needed? Assuming the action running this has fetched enough history.
            merge_base = run_command(f"git merge-base {base} {ref}", cwd)
            debug(f"Merge base is {merge_base}")
            cmd = f"git diff --name-only {merge_base} {ref}"
        except Exception:
            # Fallback if merge-base fails (e.g. shallow clone), just diff directly
            debug("Could not determine merge-base, diffing directly")
            cmd = f"git diff --name-only {base} {ref}"
    elif base:
        # Diff against base (assuming HEAD is ref)
        cmd = f"git diff --name-only {base}"
    else:
        # No base provided, maybe try to diff against previous commit?
        debug("No base/ref provided, diffing HEAD^ HEAD")
        try:
            # Check if HEAD^ exists. If not, it's likely a root commit.
            subprocess.run(["git", "rev-parse", "--verify", "HEAD^"],
                           cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cmd = "git diff --name-only HEAD^ HEAD"
        except subprocess.CalledProcessError:
            debug("HEAD^ not found, assuming root commit. Diffing against empty tree.")
            # This is the well-known Git SHA for an "empty tree" (a tree with no files).
            # Diffing against this is the standard way to get a list of all files in the current commit
            # as if they were all newly added.
            EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            cmd = f"git diff --name-only {EMPTY_TREE} HEAD"

    output = run_command(cmd, cwd)
    return [line.strip() for line in output.splitlines() if line.strip()]

def get_event_data():
    """Read and parse the GitHub event payload from file."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            debug("Failed to parse GITHUB_EVENT_PATH json")
    return {}

def glob_to_regex(pattern):
    """
    Convert a simplified glob pattern to a regex pattern.
    Supports:
        *  : Matches any character except path separator
        ** : Matches any character including path separator (recursive)
        ?  : Matches single character
    """
    parts = pattern.split('/')
    regex_parts = []
    for i, part in enumerate(parts):
        if part == '**':
            regex_parts.append('__RECURSIVE__')
        else:
            p = ''
            for c in part:
                if c == '*':
                    p += '[^/]*'
                elif c == '?':
                    p += '.'
                else:
                    p += re.escape(c)
            regex_parts.append(p)

    res = ''
    for i, part in enumerate(regex_parts):
        if part == '__RECURSIVE__':
            # Special handling for ** to match zero or more directories
            if i == 0:
                if i < len(regex_parts) - 1:
                    res += '(?:.*/)?'
                else:
                    res += '.*'
            else:
                if i == len(regex_parts) - 1:
                    res += '(?:/.*)?'
                else:
                    res += '(?:/.*)?/'
        else:
            if i > 0 and regex_parts[i-1] != '__RECURSIVE__':
                res += '/'
            res += part

    return re.compile(f'^{res}$')

def parse_filters(filters_input):
    """
    Parse filters input string.
    Tries JSON first, then YAML.
    Includes a lightweight fallback YAML parser if PyYAML is missing.
    """
    # Try parsing as JSON first
    filters_input = filters_input.strip()
    if filters_input.startswith('{'):
        try:
            return json.loads(filters_input)
        except json.JSONDecodeError:
            pass

    # Try YAML
    try:
        import yaml
        return yaml.safe_load(filters_input)
    except ImportError:
        debug("PyYAML not found. If your filters are in YAML format, please install PyYAML.")
        # Fallback simplistic YAML parser for simple keys and lists
        # Very fragile, but better than nothing for basic cases
        filters = {}
        current_key = None
        for line in filters_input.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.endswith(':'):
                current_key = line[:-1].strip()
                filters[current_key] = []
            elif line.startswith('- ') and current_key:
                val = line[2:].strip()
                # Remove quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                filters[current_key].append(val)
        return filters

def main():
    filters_input = os.environ.get("INPUT_FILTERS", "")
    input_base = os.environ.get("INPUT_BASE", "")
    input_ref = os.environ.get("INPUT_REF", "")
    working_directory = os.environ.get("INPUT_WORKING_DIRECTORY", ".")
    list_files_format = os.environ.get("INPUT_LIST_FILES", "none")

    if not filters_input:
        print("::error::filters input is required")
        sys.exit(1)

    # Determine base and ref from event payload if possible
    # This aligns logic with dorny/paths-filter behavior
    event = get_event_data()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    base = input_base
    ref = input_ref

    if event_name == "pull_request":
        debug("Detected pull_request event, using PR base/head")
        base = event.get("pull_request", {}).get("base", {}).get("sha")
        ref = event.get("pull_request", {}).get("head", {}).get("sha")
    elif event_name == "push":
        debug("Detected push event")
        if not input_base:
            # If input base is not provided, try to use 'before' from event
            before = event.get("before")
            # The 'before' SHA will be all zeros (NULL_SHA) if the branch was just created (pushed new).
            # In that case, there is no "before" commit to diff against on this branch.
            # We only use 'before' as base if it's a valid commit SHA.
            NULL_SHA = "0000000000000000000000000000000000000000"
            if before and before != NULL_SHA:
                base = before

        if not input_ref:
            ref = os.environ.get("GITHUB_SHA")

    debug(f"Resolved base: {base}, ref: {ref}")

    filters = parse_filters(filters_input)
    debug(f"Parsed filters: {filters}")

    try:
        changed_files = get_commits(base, ref, working_directory)
        debug(f"Changed files: {changed_files}")
    except Exception as e:
        print(f"::error::Failed to get changed files: {e}")
        sys.exit(1)

    changes = []

    # Match changed files against filters
    for filter_name, patterns in filters.items():
        if isinstance(patterns, str):
            patterns = [patterns]

        is_match = False
        matched_files = []

        for pattern in patterns:
            # Handle inclusion/exclusion logic if pattern starts with !?
            # For simplicity, assuming basic inclusion globs for now,
            # ignoring the complex ! logic for this MVP unless strictly needed.
            # But normally ! means exclude.

            # Simple positive match for now
            regex = glob_to_regex(pattern)
            for file in changed_files:
                if regex.match(file):
                    if file not in matched_files:
                        matched_files.append(file)
                    is_match = True

        set_output(filter_name, 'true' if is_match else 'false')
        set_output(f"{filter_name}_count", len(matched_files))

        if is_match:
            changes.append(filter_name)

        # List files output
        if list_files_format != 'none' and matched_files:
            if list_files_format == 'json':
                set_output(f"{filter_name}_files", json.dumps(matched_files))
            elif list_files_format == 'csv':
                set_output(f"{filter_name}_files", ",".join(matched_files))
            elif list_files_format == 'shell':
                 set_output(f"{filter_name}_files", " ".join(shlex.quote(f) for f in matched_files))
            elif list_files_format == 'escape':
                 set_output(f"{filter_name}_files", " ".join(f.replace(' ', '\\ ') for f in matched_files)) # simplified escape
            else:
                 # Default to space separated? Or just ignore unknown formats
                 pass

    set_output("changes", json.dumps(changes))

if __name__ == "__main__":
    main()
