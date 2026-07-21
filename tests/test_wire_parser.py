import unittest
from unittest.mock import patch

from services import wire_parser


class WireParserCacheTests(unittest.TestCase):
    def setUp(self):
        self.caches = (
            wire_parser._parse_cache,
            wire_parser._trend_cache,
            wire_parser._tool_usage_cache,
            wire_parser._model_usage_cache,
        )
        self.saved = [cache.copy() for cache in self.caches]
        for cache in self.caches:
            cache.update(data=None, at=0.0, date=None)

    def tearDown(self):
        for cache, saved in zip(self.caches, self.saved):
            cache.clear()
            cache.update(saved)

    def test_high_level_usage_getters_share_one_full_parse(self):
        parsed = wire_parser.ParseResult()
        with patch.object(wire_parser, "parse_all_full", return_value=parsed) as parse_all:
            wire_parser.get_tool_usage()
            wire_parser.get_model_usage()
            wire_parser.get_trends()

        parse_all.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
