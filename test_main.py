import unittest
import re
from main import glob_to_regex, parse_filters

class TestPathsFilter(unittest.TestCase):
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
        # Testing the manual fallback parser
        filters_str = """
        src:
          - src/**
        test:
          - 'test/**'
        """
        filters = parse_filters(filters_str)
        self.assertEqual(filters["src"], ["src/**"])
        self.assertEqual(filters["test"], ["test/**"])

if __name__ == '__main__':
    unittest.main()
