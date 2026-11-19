"""Regression test for the replace template filter (score_extras)."""

from django.template import Template, Context
from django.test import TestCase


class ReplaceFilterTest(TestCase):
    def test_replaces_substring(self):
        t = Template("{% load score_extras %}{{ value|replace:'test_,Test ' }}")
        result = t.render(Context({"value": "test_1"}))
        self.assertEqual(result.strip(), "Test 1")

    def test_no_match_returns_original(self):
        t = Template("{% load score_extras %}{{ value|replace:'foo_,Bar ' }}")
        result = t.render(Context({"value": "test_1"}))
        self.assertEqual(result.strip(), "test_1")

    def test_none_value_returns_empty(self):
        t = Template("{% load score_extras %}{{ value|replace:'test_,Test ' }}")
        result = t.render(Context({"value": None}))
        self.assertEqual(result.strip(), "")
