#!/usr/bin/env python3.6

import os.path
import sys
import unittest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
)

from vodokanal import (
    VodokanalNewsDetailsParser,
    VodokanalParser,
    get_news_data,
    get_news_index_data,
)


class ParserCompatTest(unittest.TestCase):
    """Parser Compatibility Test

    Vodokanal changes their website all the time, try to check
    if the parser still works.
    """

    def test_parser(self):
        data = get_news_index_data()

        parser = VodokanalParser()
        parser.feed(data)

        self.assertGreater(len(parser._news_links), 0)

        _, news_url = parser._news_links.popitem()

        news_data = get_news_data(news_url)

        news_item_parser = VodokanalNewsDetailsParser()
        news_item_parser.feed(news_data)
        news_item = news_item_parser.get_item()


if __name__ == "__main__":
    unittest.main()
