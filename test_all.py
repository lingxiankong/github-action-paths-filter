#!/usr/bin/env python3
import unittest
import os
import shutil
import subprocess
import json
import textwrap
import re
from main import glob_to_regex, parse_filters

# --- Unit Tests ---
class TestUnit(unittest.TestCase):
    def test_glob_to_regex_simple(self):
        regex = glob_to_regex("*.py")
        self.assertTrue(regex.match("main.py"))
        self.assertFalse(regex.match("main.js"))
        self.assertFalse(regex.match("dir/main.py"))

    def test_glob_to_regex_recursive(self):
        regex = glob_to_regex("**/*.py")
        self.assertTrue(regex.match("main.py"))
        self.assertTrue(regex.match("dir/main.py"))
        self.assertTrue(regex.match("dir/sub/main.py"))
        self.assertFalse(regex.match("main.js"))

    def test_glob_to_regex_specific_dir(self):
        regex = glob_to_regex("src/**")
        self.assertTrue(regex.match("src/main.py"))
        self.assertTrue(regex.match("src/utils/helper.py"))
        self.assertFalse(regex.match("test/main.py"))

    def test_parse_filters_json(self):
        filters_str = '{"src": ["src/**"], "test": ["test/**"]}'
        filters = parse_filters(filters_str)
        self.assertEqual(filters["src"], ["src/**"])
        self.assertEqual(filters["test"], ["test/**"])

    def test_parse_filters_yaml_simple(self):
        filters_str = textwrap.dedent("""
        src:
          - src/**
        test:
          - 'test/**'
        """)
        filters = parse_filters(filters_str)
        self.assertEqual(filters["src"], ["src/**"])
        self.assertEqual(filters["test"], ["test/**"])

# --- Helper for integration tests ---
def run_git_cmd(cmd, cwd):
    subprocess.check_call(cmd, cwd=cwd, shell=True)

class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_repo_integration"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)

        run_git_cmd("git init", self.test_dir)
        run_git_cmd('git config user.email "you@example.com"', self.test_dir)
        run_git_cmd('git config user.name "Your Name"', self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        if os.path.exists("event.json"):
            os.remove("event.json")

    def test_push_root_commit(self):
        # Simulate a pure root commit push
        # This tests the "diff against empty tree" logic in main.py
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir)

        run_git_cmd("git init", self.test_dir)
        # We need config for commit
        run_git_cmd('git config user.email "you@example.com"', self.test_dir)
        run_git_cmd('git config user.name "Your Name"', self.test_dir)

        # Create one file
        with open(os.path.join(self.test_dir, "file1.txt"), "w") as f: f.write("content")
        run_git_cmd("git add .", self.test_dir)
        run_git_cmd('git commit -m "Root commit"', self.test_dir)

        # Mock Event: Push with before=0000... (NULL_SHA)
        event_data = {
            "before": "0000000000000000000000000000000000000000",
            "after": "HEAD_SHA", # Doesn't matter much for our logic
        }
        with open("event.json", "w") as f:
            json.dump(event_data, f)

        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = os.path.abspath("event.json")
        env["GITHUB_EVENT_NAME"] = "push"
        # Filters to match everything
        env["INPUT_FILTERS"] = '{"all": ["**"]}'
        env["INPUT_WORKING_DIRECTORY"] = self.test_dir
        # No input base/ref provided
        if "INPUT_BASE" in env: del env["INPUT_BASE"]
        if "INPUT_REF" in env: del env["INPUT_REF"]

        result = subprocess.run(
            ["python3", "main.py"],
            cwd=".",
            env=env,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")

        self.assertEqual(result.returncode, 0)
        output = result.stdout

        # Should detect the new file
        self.assertIn("::set-output name=all::true", output)
        self.assertIn("::set-output name=all_count::1", output)

    def test_end_to_end_manual_verify(self):
        # Commit 1
        os.makedirs(os.path.join(self.test_dir, "src"))
        os.makedirs(os.path.join(self.test_dir, "doc"))
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f: f.write("")
        with open(os.path.join(self.test_dir, "doc", "readme.md"), "w") as f: f.write("")
        run_git_cmd("git add .", self.test_dir)
        run_git_cmd('git commit -m "Initial commit"', self.test_dir)
        base_sha = subprocess.check_output("git rev-parse HEAD", cwd=self.test_dir, shell=True, universal_newlines=True).strip()

        # Commit 2
        with open(os.path.join(self.test_dir, "src", "utils.py"), "w") as f: f.write("")
        with open(os.path.join(self.test_dir, "src", "main.py"), "w") as f: f.write("change")
        run_git_cmd("git add .", self.test_dir)
        run_git_cmd('git commit -m "Add utils and modify main"', self.test_dir)
        ref_sha = subprocess.check_output("git rev-parse HEAD", cwd=self.test_dir, shell=True, universal_newlines=True).strip()

        # Prepare Env
        env = os.environ.copy()
        env["INPUT_FILTERS"] = '{"src": ["src/**"], "doc": ["doc/**"]}'
        env["INPUT_BASE"] = base_sha
        env["INPUT_REF"] = ref_sha
        env["INPUT_LIST_FILES"] = "csv"
        env["INPUT_WORKING_DIRECTORY"] = self.test_dir
        # We need to capture output via set-output, which prints to stdout/GITHUB_OUTPUT
        # To simplify, we'll read stdout

        # Run main.py
        result = subprocess.run(
            ["python3", "main.py"],
            cwd=".",
            env=env,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")

        self.assertEqual(result.returncode, 0)
        output = result.stdout

        # Checking output...
        # Note: In local mode without GITHUB_OUTPUT, it prints ::set-output
        self.assertIn("::set-output name=src::true", output)
        self.assertIn("::set-output name=doc::false", output)
        self.assertIn("::set-output name=src_files::src/main.py,src/utils.py", output)


    def test_pull_request_event_logic(self):
        # Commit 1
        with open(os.path.join(self.test_dir, "base_file"), "w") as f: f.write("")
        run_git_cmd("git add .", self.test_dir)
        run_git_cmd('git commit -m "Base commit"', self.test_dir)
        base_sha = subprocess.check_output("git rev-parse HEAD", cwd=self.test_dir, shell=True, universal_newlines=True).strip()

        # Commit 2
        with open(os.path.join(self.test_dir, "head_file"), "w") as f: f.write("")
        run_git_cmd("git add .", self.test_dir)
        run_git_cmd('git commit -m "Head commit"', self.test_dir)
        head_sha = subprocess.check_output("git rev-parse HEAD", cwd=self.test_dir, shell=True, universal_newlines=True).strip()

        # Create event.json
        event_data = {
            "pull_request": {
                "base": {"sha": base_sha},
                "head": {"sha": head_sha}
            }
        }
        with open("event.json", "w") as f:
            json.dump(event_data, f)

        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = os.path.abspath("event.json")
        env["GITHUB_EVENT_NAME"] = "pull_request"
        env["INPUT_FILTERS"] = '{"all": ["**"]}'
        env["INPUT_WORKING_DIRECTORY"] = self.test_dir
        env["INPUT_BASE"] = "wrong_base" # To test override

        result = subprocess.run(
            ["python3", "main.py"],
            cwd=".",
            env=env,
            capture_output=True,
            text=True
        )

        self.assertEqual(result.returncode, 0)
        output = result.stdout

        self.assertIn("Detected pull_request event, using PR base/head", output)
        self.assertIn(f"Resolved base: {base_sha}", output)
        self.assertIn("::set-output name=all::true", output)

if __name__ == '__main__':
    unittest.main()
