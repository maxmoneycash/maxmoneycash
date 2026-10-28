import unittest

from model_pricing import reference_cost, reference_price, list_value


class ModelPricingTests(unittest.TestCase):
    def test_published_generations(self):
        for name, rates in [
            ("claude-opus-5-5", (4, 20, 0.2, 5)),
            ("claude-opus-5-5-fast", (8, 40, 0.4, 10)),
            ("claude-opus-4-8", (5, 25, 0.5, 6.25)),
            ("claude-fable-5-1", (10, 50, 0.25, 12.5)),
            ("claude-fable-5", (10, 50, 1, 12.5)),
            ("claude-sonnet-5", (2, 10, 0.2, 2.5)),
            ("claude-haiku-4-5", (1, 5, 0.1, 1.25)),
            ("claude-haiku-5-5", (0.1, 0.5, 0.01, 0.125)),
            ("gpt-6-astra", (10, 50, 1, 12.5)),
            ("gpt-6-sol", (2, 10, 0.2, 2.5)),
            ("gpt-6.1-sol", (2, 10, 0.1, 2.5)),
            ("gpt-5.6-sol", (4, 20, 0.4, 5)),
            ("gpt-5.3-codex", (1.75, 14, 0.175, 1.75)),
        ]:
            with self.subTest(name=name):
                self.assertEqual(reference_price(name), rates)

    def test_aliases_and_snapshot_ids(self):
        for name in ["CLAUDE-OPUS-5.5", "anthropic/claude-opus-5-5",
                     "cursor-claude-opus-5-5-thinking-high", "claude-opus-5-5-20260901"]:
            self.assertEqual(reference_price(name), (4, 20, 0.2, 5), name)
        self.assertEqual(reference_price("claude-4.5-opus-thinking"), (5, 25, 0.5, 6.25))
        self.assertEqual(reference_price("[openclaw] gpt-5.6-sol"), (4, 20, 0.4, 5))
        self.assertEqual(reference_price("gpt-5.5-2026-04-23"), reference_price("gpt-5.5"))
        self.assertEqual(reference_price("gpt-6.1-sol-2026-09-29"), reference_price("gpt-6.1-sol"))
        self.assertNotEqual(reference_price("claude-opus-5-50"), (4, 20, 0.2, 5))
        self.assertNotEqual(reference_price("gpt-5.5-pro"), reference_price("gpt-5.5"))
        self.assertNotEqual(reference_price("gpt-6-sol-fast"), reference_price("gpt-6-sol"))
        self.assertEqual(reference_price("claude-opus-4-1"), (15, 75, 1.5, 18.75))

    def test_real_costs_survive_and_free_models_stay_free(self):
        row = {"cacheReadTokens": 1_000_000_000, "cost": 321.5}
        self.assertEqual(reference_cost("claude-opus-5-5", row), 200)
        self.assertEqual(list_value("claude-opus-5-5", row), 321.5)
        self.assertEqual(reference_cost("claude-opus-5-5-free", row), 0)
        self.assertEqual(reference_cost("unknown-model", row), 0)
        self.assertIsNone(reference_price(None))


if __name__ == "__main__":
    unittest.main()
