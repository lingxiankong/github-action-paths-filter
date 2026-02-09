import os
import sys
import subprocess
import json
import re
import shlex

def debug(msg):
    print(f"::debug::{msg}")

def set_output(name, value):
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{name}={value}\n")
    else:
        # Fallback for local testing
        print(f"::set-output name={name}::{value}")

def run_command(command, cwd=None):
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

def get_changed_files(base, ref, cwd):
    # If base is not provided, we might be in a push event or generic context
    # But usually base is required for PRs.
    # For now, let's assume we can use git diff.

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
        # Or if it's a push event, HEAD^ HEAD?
        # dorny/paths-filter usually defaults base to 'master' if not provided for PRs.
        # But here we execute what we are given.
        # If nothing given, try HEAD^...HEAD
        debug("No base/ref provided, diffing HEAD^ HEAD")
        cmd = "git diff --name-only HEAD^ HEAD"

    output = run_command(cmd, cwd)
    return [line.strip() for line in output.splitlines() if line.strip()]

def glob_to_regex(pattern):
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
    token = os.environ.get("INPUT_TOKEN", "")
    filters_input = os.environ.get("INPUT_FILTERS", "")
    base = os.environ.get("INPUT_BASE", "")
    ref = os.environ.get("INPUT_REF", "")
    working_directory = os.environ.get("INPUT_WORKING_DIRECTORY", ".")
    list_files_format = os.environ.get("INPUT_LIST_FILES", "none")

    if not filters_input:
        print("::error::filters input is required")
        sys.exit(1)

    filters = parse_filters(filters_input)
    debug(f"Parsed filters: {filters}")

    try:
        changed_files = get_changed_files(base, ref, working_directory)
        debug(f"Changed files: {changed_files}")
    except Exception as e:
        print(f"::error::Failed to get changed files: {e}")
        sys.exit(1)

    changes = []

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
