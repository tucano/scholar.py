#! /usr/bin/env python
"""
This module provides classes for querying Google Scholar and parsing
returned results.  It currently *only* processes the first results
page.  It is not a recursive crawler.
"""
# Version: 1.5 -- $Date: 2012-09-27 10:44:39 -0700 (Thu, 27 Sep 2012) $
#
# ChangeLog
# ---------
#
# 1.6:  Cookie support, from Matej Smid (https://github.com/palmstrom).
#
# 1.5:  A few changes:
#
#       - Tweak suggested by Tobias Isenberg: use unicode during CSV
#         formatting.
#
#       - The option -c|--count now understands numbers up to 100 as
#         well. Likewise suggested by Tobias.
#
#       - By default, text rendering mode is now active. This avoids
#         confusion when playing with the script, as it used to report
#         nothing when the user didn't select an explicit output mode.
#
# 1.4:  Updates to reflect changes in Scholar's page rendering,
#       contributed by Amanda Hay at Tufts -- thanks!
#
# 1.3:  Updates to reflect changes in Scholar's page rendering.
#
# 1.2:  Minor tweaks, mostly thanks to helpful feedback from Dan Bolser.
#       Thanks Dan!
#
# 1.1:  Made author field explicit, added --author option.
#
# pylint: disable-msg=C0111
#
# Copyright 2010--2013 Christian Kreibich. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#    1. Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import optparse
import sys
import re
import urllib
import urllib2
from BeautifulSoup import BeautifulSoup
from cookielib import CookieJar

class Article():
    """
    A class representing articles listed on Google Scholar.  The class
    provides basic dictionary-like behavior.
    """
    def __init__(self):
        self.attrs = {'title':         [None, 'Title',          0],
                      'authors':       [None, 'Authors',        1],
                      'url':           [None, 'URL',            2],
                      'num_citations': [0,    'Citations',      3],
                      'num_versions':  [0,    'Versions',       4],
                      'url_citations': [None, 'Citations list', 5],
                      'url_versions':  [None, 'Versions list',  6],
                      'year':          [None, 'Year',           7],
                      'journal':       [None, 'Journal',        8]}

    def __getitem__(self, key):
        if key in self.attrs:
            return self.attrs[key][0]
        return None

    def __setitem__(self, key, item):
        if key in self.attrs:
            self.attrs[key][0] = item
        else:
            self.attrs[key] = [item, key, len(self.attrs)]

    def __delitem__(self, key):
        if key in self.attrs:
            del self.attrs[key]

    def as_txt(self):
        # Get items sorted in specified order:
        items = sorted(self.attrs.values(), key=lambda item: item[2])
        # Find largest label length:
        max_label_len = max([len(str(item[1])) for item in items])
        fmt = '%%%ds %%s' % max_label_len
        return '\n'.join([fmt % (item[1], item[0]) for item in items])

    def as_csv(self, header=False, sep='|'):
        # Get keys sorted in specified order:
        keys = [pair[0] for pair in \
                    sorted([(key, val[2]) for key, val in self.attrs.items()],
                           key=lambda pair: pair[1])]
        res = []
        if header:
            res.append(sep.join(keys))
        res.append(sep.join([unicode(self.attrs[key][0]) for key in keys]))
        return '\n'.join(res)

class ScholarParser():
    """
    ScholarParser can parse HTML document strings obtained from Google
    Scholar. It invokes the handle_article() callback on each article
    that was parsed successfully.
    """
    SCHOLAR_SITE = 'http://scholar.google.com'

    def __init__(self, site=None):
        self.soup = None
        self.article = None
        self.site = site or self.SCHOLAR_SITE
        self.year_re = re.compile(r'\b(?:20|19)\d{2}\b')

    def handle_article(self, art):
        """
        In this base class, the callback does nothing.
        """

    def parse(self, html):
        """
        This method initiates parsing of HTML content.
        """
        self.soup = BeautifulSoup(html)
        for div in self.soup.findAll(ScholarParser._tag_checker):
            self._parse_article(div)

    def _parse_article(self, div):
        self.article = Article()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'div' and tag.get('class') == 'gs_rt' and \
                    tag.h3 and tag.h3.a:
                self.article['title'] = ''.join(tag.h3.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.h3.a['href'])

            if tag.name == 'font':
                for tag2 in tag:
                    if not hasattr(tag2, 'name'):
                        continue
                    if tag2.name == 'span' and tag2.get('class') == 'gs_fl':
                        self._parse_links(tag2)

        if self.article['title']:
            self.handle_article(self.article)

    def _parse_links(self, span):
        for tag in span:
            if not hasattr(tag, 'name'):
                continue
            if tag.name != 'a' or tag.get('href') == None:
                continue

            if tag.get('href').startswith('/scholar?cites'):
                if hasattr(tag, 'string') and tag.string.startswith('Cited by'):
                    self.article['num_citations'] = \
                        self._as_int(tag.string.split()[-1])
                self.article['url_citations'] = self._path2url(tag.get('href'))

            if tag.get('href').startswith('/scholar?cluster'):
                if hasattr(tag, 'string') and tag.string.startswith('All '):
                    self.article['num_versions'] = \
                        self._as_int(tag.string.split()[1])
                self.article['url_versions'] = self._path2url(tag.get('href'))

    @staticmethod
    def _tag_checker(tag):
        if tag.name == 'div' and tag.get('class') == 'gs_r':
            return True
        return False

    def _as_int(self, obj):
        try:
            return int(obj)
        except ValueError:
            return None

    def _path2url(self, path):
        if path.startswith('http://'):
            return path
        if not path.startswith('/'):
            path = '/' + path
        return self.site + path

class ScholarParser120201(ScholarParser):
    """
    This class reflects update to the Scholar results page layout that
    Google recently.
    """

    def _parse_article(self, div):
        self.article = Article()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'h3' and tag.get('class') == 'gs_rt' and tag.a:
                self.article['title'] = ''.join(tag.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.a['href'])

            if tag.name == 'div' and tag.get('class') == 'gs_a':
                year = self.year_re.findall(tag.text)
                self.article['year'] = year[0] if len(year) > 0 else None

            if tag.name == 'div' and tag.get('class') == 'gs_fl':
                self._parse_links(tag)

        if self.article['title']:
            self.handle_article(self.article)

class ScholarParser120726(ScholarParser):
    """
    This class reflects update to the Scholar results page layout that
    Google made 07/26/12.
    """

    def _parse_article(self, div):
        self.article = Article()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'div' and tag.get('class') == 'gs_ri':
              if tag.a:
                self.article['title'] = ''.join(tag.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.a['href'])

              if tag.find('div', {'class': 'gs_a'}):
                year = self.year_re.findall(tag.find('div', {'class': 'gs_a'}).text)
                self.article['year'] = year[0] if len(year) > 0 else None

              if tag.find('div', {'class': 'gs_fl'}):
                self._parse_links(tag.find('div', {'class': 'gs_fl'}))

        if self.article['title']:
            self.handle_article(self.article)


class ScholarQuerier():
    """
    ScholarQuerier instances can conduct a search on Google Scholar
    with subsequent parsing of the resulting HTML content.  The
    articles found are collected in the articles member, a list of
    Article instances.
    """
    SCHOLAR_URL = 'http://scholar.google.com/scholar?hl=en&q=%(query)s+author:%(author)s&btnG=Search&as_subj=eng&as_sdt=1,5&as_ylo=&as_vis=0'
    NOAUTH_URL = 'http://scholar.google.com/scholar?hl=en&q=%(query)s&btnG=Search&as_subj=eng&as_std=1,5&as_ylo=&as_vis=0'
    SEARCH_AUTHOR_URL = 'http://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=%(author)s'
    """
    Older URLs:
    http://scholar.google.com/scholar?q=%s&hl=en&btnG=Search&as_sdt=2001&as_sdtp=on
    """

    UA = 'Mozilla/5.0 (X11; U; FreeBSD i386; en-US; rv:1.9.2.9) Gecko/20100913 Firefox/3.6.9'

    class Parser(ScholarParser120726):
        def __init__(self, querier):
            ScholarParser.__init__(self)
            self.querier = querier

        def handle_article(self, art):
            self.querier.add_article(art)

    class AuthorParser():
        """
        Parser for the author page. Version date: 5 Dec 2013
        """
        PAGE_SIZE = '&view_op=list_works&pagesize=100'

        def __init__(self, querier):
            self.soup = None
            self.querier = querier
            self.author_url_pattern = '/citations?user='

        def parse(self, html):
            """
            This method initiates parsing of HTML content for an author page.
            It serach for a link with href = citations?user=XXXXXXXXXX=en
            """
            self.soup = BeautifulSoup(html)
            for link in self.soup.findAll('a'):
                s = ScholarParser.SCHOLAR_SITE + link.get('href') + self.PAGE_SIZE
                if self.author_url_pattern in s:
                    return s

    class ViewCitationParser():
        """
            Parser for the view citation page. Version date: 5 Dec 2013
        """

        def __init__(self, querier):
            self.soup = None
            self.querier = querier
            self.article_info = {}

        def parse(self, html):
            """
            This method initiates parsing of HTML content for a citation view page.
            """
            self.soup = BeautifulSoup(html)
            td_content_cell = self.soup.find(self._tag_checker)
            self.article_info['url'] = td_content_cell.find(id='title').a.get('href')
            for link in td_content_cell.findAll('a'):
                url = link.get('href')
                if ('&cluster=' in url) and (not url.endswith('&btnI=Lucky')):
                    self.article_info['url_versions'] = link.get('href')
                    self.article_info['num_versions'] = self._as_int(link.getText().split()[1])
            return self.article_info

        def _tag_checker(self, tag):
            if tag.name == 'td' and tag.get('class') == 'cit-contentcell':
                return True
            return False

        def _as_int(self, obj):
            try:
                return int(obj)
            except ValueError:
                return None

    class CitationParser():
        """
        Parser for the author citation page. It invokes the handle_article() callback on each article
    that was parsed successfully. Version date: 5 Dec 2013
        """

        def __init__(self, querier):
            self.soup = None
            self.querier = querier
            self.site = ScholarParser.SCHOLAR_SITE

        def parse(self, html):
            """
            This method initiates parsing of HTML content for an author citation page.
            It serach for a table
            """
            self.soup = BeautifulSoup(html)
            for tr in self.soup.findAll(self._tag_checker):
                self._parse_article(tr)

        def handle_article(self, art):
            self.querier.add_article(art)

        def _parse_article(self, tr):
            self.article  = Article()
            tag_article   = tr.find(id='col-title')
            tag_citations = tr.find(id='col-citedby')
            tag_year      = tr.find(id='col-year')

            self.article['title'] = tag_article.a.getText()
            # get the url for the citation view page I reclycle the ScholarQuery class ...
            url = self._path2url(tag_article.a.get('href'))
            querier = ScholarQuerier(self)
            article_info = querier.query_citation_view(url)

            if article_info.has_key('url'):
                self.article['url'] = article_info['url']

            if article_info.has_key('url_versions'):
                self.article['num_versions'] = article_info['num_versions']
                self.article['url_versions'] = article_info['url_versions']

            spans = tag_article.findAll('span')
            if (len(spans) > 0):
                self.article['authors']       = spans[0].getText()
                if (len(spans) > 1):
                    self.article['journal']       = spans[1].getText()

            if tag_citations.getText() != "":
                self.article['num_citations'] = self._as_int(tag_citations.a.getText())
                self.article['url_citations'] = self._path2url(tag_citations.a.get('href'))

            self.article['year']          = tag_year.getText()

            if self.article['title']:
                self.handle_article(self.article)

        def _tag_checker(self, tag):
            if tag.name == 'tr' and tag.get('class') == 'cit-table item':
                return True
            return False

        def _as_int(self, obj):
            try:
                return int(obj)
            except ValueError:
                return None

        def _path2url(self, path):
            if path.startswith('http://'):
                return path
            if not path.startswith('/'):
                path = '/' + path
            return self.site + path

    def __init__(self, author='', scholar_url=None, count=0, search_author=False):
        self.articles = []
        self.author = author
        self.search_author = search_author

        # Clip to 100, as Google doesn't support more anyway
        self.count = min(count, 100)

        if author == '':
            self.scholar_url = self.NOAUTH_URL
        elif search_author:
            self.scholar_url = self.SEARCH_AUTHOR_URL
        else:
            self.scholar_url = scholar_url or self.SCHOLAR_URL

        if self.count != 0:
            self.scholar_url += '&num=%d' % self.count

        self.cjar = CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cjar))

    def query(self, search):
        """
        This method initiates a query with subsequent parsing of the
        response.
        """
        self.clear_articles()
        url = self.scholar_url % {'query': urllib.quote(search.encode('utf-8')), 'author': urllib.quote(self.author)}
        req = urllib2.Request(url=url,
                              headers={'User-Agent': self.UA})
        hdl = self.opener.open(req)
        html = hdl.read()
        self.parse(html)

    def query_author(self, search):
        """
        This method initiates a query using the search author google scholar query
        """
        self.clear_articles()
        url = self.scholar_url % {'author' : urllib.quote(self.author)}
        req = urllib2.Request(url=url,
                              headers={'User-Agent': self.UA})
        hdl = self.opener.open(req)
        html = hdl.read()
        author_url = self.parse_author_page(html)
        req = urllib2.Request(url=author_url,
                              headers={'User-Agent': self.UA})
        hdl = self.opener.open(req)
        html = hdl.read()
        self.parse_citation_page(html)

    def parse(self, html):
        """
        This method allows parsing of existing HTML content.
        """
        parser = self.Parser(self)
        parser.parse(html)

    def parse_author_page(self, html):
        """
        This method allows parsing of an author page.
        """
        parser = self.AuthorParser(self)
        return parser.parse(html)

    def parse_citation_page(self, html):
        """
        This method allows parsing of an author citation page.
        """
        parser = self.CitationParser(self)
        return parser.parse(html)

    def add_article(self, art):
        self.articles.append(art)

    def clear_articles(self):
        """Clears any existing articles stored from previous queries."""
        self.articles = []

    def query_citation_view(self, url):
        """
        This method initiates a query using the citation view url
        """
        req = urllib2.Request(url=url,
                              headers={'User-Agent': self.UA})
        hdl = self.opener.open(req)
        html = hdl.read()
        return self.parse_citation_view(html)

    def parse_citation_view(self, html):
        parser = self.ViewCitationParser(self)
        return parser.parse(html)


def txt(query, author, count, search_author):
    querier = ScholarQuerier(author=author, count=count, search_author=search_author)

    if search_author:
        querier.query_author(query)
    else:
        querier.query(query)

    articles = querier.articles
    if count > 0:
        articles = articles[:count]
    for art in articles:
        print art.as_txt() + '\n'

def csv(query, author, count, search_author, header=False, sep='|'):
    querier = ScholarQuerier(author=author, count=count, search_author=search_author)

    if search_author:
        querier.query_author(query)
    else:
        querier.query(query)

    articles = querier.articles
    if count > 0:
        articles = articles[:count]
    for art in articles:
        result = art.as_csv(header=header, sep=sep)
        print result.encode('utf-8')
        header = False

def url(title, author):
    querier = ScholarQuerier(author=author)
    querier.query(title)
    articles = querier.articles
    for article in articles:
        if "".join(title.lower().split()) == "".join(article['title'].lower().split()):
            return article['url'], article['year']
    return None, None

def titles(author):
    querier = ScholarQuerier(author=author)
    querier.query('')
    articles = querier.articles
    titles = []
    for article in articles:
      titles.append(article['title'])
    return titles

def main():
    usage = """scholar.py [options] <query string>
A command-line interface to Google Scholar."""

    fmt = optparse.IndentedHelpFormatter(max_help_position=50,
                                         width=100)
    parser = optparse.OptionParser(usage=usage, formatter=fmt)
    parser.add_option('-a', '--author',
                      help='Author name')
    parser.add_option('-s', '--search-author', action='store_true',
                      help='Use profile search author')
    parser.add_option('--csv', action='store_true',
                      help='Print article data in CSV format (separator is "|")')
    parser.add_option('--csv-header', action='store_true',
                      help='Like --csv, but print header line with column names')
    parser.add_option('--txt', action='store_true',
                      help='Print article data in text format')
    parser.add_option('-c', '--count', type='int',
                      help='Maximum number of results')
    parser.set_defaults(count=0, author='')
    options, args = parser.parse_args()

    # in search author mode i don't need a query string
    if ((len(args) == 0) and (not options.search_author)):
        print 'Hrrrm. I  need a query string.'
        sys.exit(1)

    query = ' '.join(args)

    #sys.stderr.write('query: ' + query + "\n")
    #sys.stderr.write('author: ' + options.author + "\n")

    if options.csv:
        csv(query, author=options.author, count=options.count, search_author=options.search_author)
    elif options.csv_header:
        csv(query, author=options.author, count=options.count, search_author=options.search_author, header=True)
    else:
        txt(query, author=options.author, count=options.count, search_author=options.search_author)

if __name__ == "__main__":
    main()
