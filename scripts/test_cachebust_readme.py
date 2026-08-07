import unittest

from cachebust_readme import stamp_image_versions


class CachebustReadmeTests(unittest.TestCase):
    def test_replaces_complete_local_and_live_versions(self):
        source = "\n".join(
            [
                '<img src="./assets/neofetch.svg?v=123-old-old"/>',
                '<source srcset="https://commits.sh/api/badge?handle=maxmoneycash&style=profile&theme=light&v=old"/>',
                '<img src="https://commits.sh/api/badge?handle=maxmoneycash&style=profile&theme=dark"/>',
            ]
        )

        stamped, count = stamp_image_versions(source, "456")

        self.assertEqual(count, 3)
        self.assertIn("assets/neofetch.svg?v=456", stamped)
        self.assertNotIn("123-old-old", stamped)
        self.assertIn("theme=light&v=456", stamped)
        self.assertIn("theme=dark&v=456", stamped)

    def test_preserves_html_escaped_query_separator(self):
        source = (
            "https://commits.sh/api/badge?handle=maxmoneycash&amp;style=wrapped"
            "&amp;theme=dark&amp;v=old"
        )

        stamped, count = stamp_image_versions(source, "789")

        self.assertEqual(count, 1)
        self.assertEqual(
            stamped,
            "https://commits.sh/api/badge?handle=maxmoneycash&amp;style=wrapped"
            "&amp;theme=dark&amp;v=789",
        )


if __name__ == "__main__":
    unittest.main()
