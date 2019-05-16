#!/usr/bin/env python3.6

from html.parser import HTMLParser
from urllib.request import urlopen
import collections
import configparser
import getopt
import logging
import re
import sqlite3
import sys

import telegram


LOGGER = logging.getLogger(__name__)


URL_BASE = 'http://kvs-saratov.ru'
VODO_URL = "http://kvs-saratov.ru/news/operativnyy-monitoring/"

NewsItem = collections.namedtuple('NewsItem', ['title', 'date', 'details'])


def get_bot(bot_token, bot_proxy):
    if bot_proxy:
        request = telegram.utils.request.Request(
            proxy_url=bot_proxy,
        )
        bot = telegram.Bot(bot_token, request=request)
    else:
        bot = telegram.Bot(bot_token)

    return bot


def get_news_index_data():
    """Get news index data"""
    f = urlopen(VODO_URL)
    return f.read().decode('utf-8')

def get_news_data(news_url):
    """Get specific news item"""
    f = urlopen(URL_BASE + news_url)
    return f.read().decode('utf-8')


class VodokanalParser(HTMLParser):
    HREF_REGEXP = "/news/operativnyy-monitoring/(?P<id>[0-9a-zA-Z_-]+)/"

    def __init__(self, *args, **kwargs):
        HTMLParser.__init__(self, *args, **kwargs)
        self._news_links = {}

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return

        dict_attrs = dict(attrs)

        if dict_attrs.get('class') == 'main_btn':
            href = dict_attrs.get('href')
            if not href:
                return
            match = re.match(self.HREF_REGEXP, href)
            if match:
                match_id = match.groupdict().get('id')
                if match_id:
                    self._news_links[match_id] = href


class VodokanalNewsDetailsParser(HTMLParser):

    def __init__(self, *args, **kwargs):
        HTMLParser.__init__(self, *args, **kwargs)
        self._in_title = False
        self._in_news_detail = False
        self._in_news_date = False
        self._title = None
        self._date = None
        self._detail = []

    def handle_starttag(self, tag, attrs):
        dict_attrs = dict(attrs)
        if tag == 'h3' and dict_attrs.get('class') == 'pagetitle':
            self._in_title = True
            return

        if tag == 'div' and dict_attrs.get('class') == 'news-detail':
            self._in_news_detail = True
            return

        if tag == 'span' and dict_attrs.get('class') == 'news-date-time':
            self._in_news_date = True
            return

    def handle_endtag(self, tag):
        if tag == 'h3':
            self._in_title = False
        elif tag == 'div':
            self._in_news_detail = False
        elif tag == 'span':
            self._in_news_date = False

    def handle_data(self, data):
        if self._in_title:
            self._title = data.strip()
        elif self._in_news_detail:
            if self._in_news_date:
                self._date = data.strip()
            else:
                data = data.strip()
                if data:
                    self._detail.append(data.strip())

    def get_item(self):
        return NewsItem(self._title, self._date, '\n'.join(self._detail))


def usage():
    print('usage: {} -c path/to/config.ini\n'.format(sys.argv[0]))
    sys.exit(2)


if __name__ == "__main__":
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'c:')
    except getopt.GetoptError as err:
        print(err)
        usage()

    config_file = None
    for o, a in opts:
        if o == '-c':
            config_file = a
        else:
            assert False, "unhandled"

    if not config_file:
        usage()

    config = configparser.ConfigParser()
    config.read(config_file)

    try:
        # db
        db_path = config['general']['db_path']

        # telegram
        tel_bot_token = config['telegram'].get('bot_token')
        tel_bot_proxy = config['telegram'].get('bot_proxy')
        tel_channel = config['telegram'].get('channel')
    except configparser.Error as err:
        print('Error reading config file: {}'.format(err))
        sys.exit(2)
    except KeyError as err:
        print('Missing required config file entry: {}'.format(err))
        sys.exit(2)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS news
        (news_id text PRIMARY KEY, title text, date date,
        created_at datetime, updated_at datetime, details text, news_url text, sent integer)'''
    )
    conn.commit()

    parser = VodokanalParser()
    parser.feed(get_news_index_data())

    for news_id, news_url in sorted(parser._news_links.items()):
        ret = c.execute('SELECT sent FROM news where news_id = ?',  (news_id,))
        db_item = ret.fetchone()
        if db_item and db_item[0] == 1:
            continue

        news_data = get_news_data(news_url)
        news_item_parser = VodokanalNewsDetailsParser()
        news_item_parser.feed(news_data)
        news_item = news_item_parser.get_item()
        if not db_item:
            c.execute('''
                INSERT INTO news (news_id, title, date, created_at, updated_at, details, news_url, sent)
                VALUES (?, ?, ?, datetime('now'), datetime('now'), ?, ?, 0)''',
                (news_id, news_item.title, news_item.date, news_item.details, URL_BASE + news_url),
            )
            conn.commit()

        # send telegram message
        msg_tokens = []
        msg_tokens.append('*' + news_item.title + '*')
        msg_tokens.append(news_item.details)

        msg_tokens.append(URL_BASE + news_url.replace("_", "\\_"))
        message = u'\n'.join(msg_tokens)

        try:
            bot = get_bot(tel_bot_token, tel_bot_proxy)
            bot.send_message(
                tel_channel, 
                message,
                parse_mode=telegram.ParseMode.MARKDOWN,
            )
        except Exception:
            LOGGER.exception('Exception while sending message')
        else:
            c.execute('UPDATE news SET sent = 1 WHERE news_id = (?)', (news_id,))
            conn.commit()
