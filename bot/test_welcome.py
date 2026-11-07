import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from bot import render_welcome_message


class WelcomePlaceholderTests(unittest.TestCase):
    def test_new_placeholders(self):
        template = "Welcome [user] | [userName] | [memberCount] | [server]"
        rendered = render_welcome_message(
            template,
            user_mention="<@123>",
            user_name="Sara",
            member_count="42",
            server_name="Creatix Hub",
        )
        self.assertEqual(
            rendered,
            "Welcome <@123> | Sara | 42 | Creatix Hub",
        )

    def test_legacy_placeholders_remain_supported(self):
        template = "Hi {member} in {server}; count={count}"
        rendered = render_welcome_message(
            template,
            user_mention="<@123>",
            user_name="Sara",
            member_count="42",
            server_name="Creatix Hub",
        )
        self.assertEqual(rendered, "Hi <@123> in Creatix Hub; count=42")

    def test_unknown_tokens_and_normal_braces_are_preserved(self):
        template = "[unknown] {notAPlaceholder} [userName]"
        rendered = render_welcome_message(
            template,
            user_mention="<@123>",
            user_name="Sara",
            member_count="42",
            server_name="Creatix Hub",
        )
        self.assertEqual(rendered, "[unknown] {notAPlaceholder} Sara")

    def test_user_name_token_is_not_partially_replaced(self):
        template = "[userName] / [user]"
        rendered = render_welcome_message(
            template,
            user_mention="<@123>",
            user_name="Sara",
            member_count="42",
            server_name="Creatix Hub",
        )
        self.assertEqual(rendered, "Sara / <@123>")


if __name__ == "__main__":
    unittest.main()
