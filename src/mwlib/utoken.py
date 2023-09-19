#! /usr/bin/env python

# Copyright (c) 2007-2009 PediaPress GmbH
# See README.rst for additional licensing information.

# unified/universal token

import re
import sys
from typing import Optional

import six

from mwlib.refine.util import parse_params, resolve_entity

from . import _uscan as _mwscan


def walknode(node, filt=lambda x: True):
    if not isinstance(node, Token):
        for x in node:
            for k in walknode(x):
                if filt(k):
                    yield k
        return

    if filt(node):
        yield node

    if node.children:
        for x in node.children:
            for k in walknode(x):
                if filt(k):
                    yield k


def walknodel(node, filt=lambda x: True):
    return list(walknode(node, filt=filt))


def show(node, out=None, indent=0, verbose=False):
    if node is None:
        return

    if out is None:
        out = sys.stdout

    if not isinstance(node, Token):
        for x in node:
            show(x, out=out, indent=indent, verbose=verbose)
        return

    out.write("{}{!r}\n".format("    " * indent, node))

    children = node.children
    if children:
        for x in children:
            show(x, out=out, indent=indent + 1, verbose=verbose)


class _Show:
    def __get__(self, obj, type=None):
        if obj is None:
            return lambda node, out=None: show(node, out=out)
        else:
            return lambda out=None: show(obj, out=out)


class Token:
    caption = ""
    vlist = None
    target = None
    level = None
    children: Optional[list] = None
    target: Optional[str] = None
    full_target = None

    rawtagname = None
    tagname = None
    ns = None
    lineprefix = None
    interwiki = None
    langlink = None
    namespace = None
    blocknode = False

    # image attributes
    align = None
    thumb = False
    frame = None

    t_end = 0
    t_text = 1
    t_entity = 2
    t_special = 3
    t_magicword = 4
    t_comment = 5
    t_2box_open = 6
    t_2box_close = 7
    t_http_url = 8
    t_break = 9
    t_begintable = t_begin_table = 10
    t_endtable = t_end_table = 11
    t_html_tag = 12
    t_singlequote = 13
    t_pre = 14
    t_section = 15
    t_endsection = t_section_end = 16

    t_item = 17
    t_colon = 18
    t_semicolon = 19
    t_hrule = 20
    t_newline = 21
    t_column = 22
    t_row = 23
    t_tablecaption = 24
    t_urllink = 25
    t_uniq = 26

    t_html_tag_end = 100

    t_complex_article = None
    t_complex_caption = None
    t_complex_compat = None
    t_complex_line = None
    t_complex_link = None
    t_complex_named_url = None
    t_complex_node = None
    t_complex_preformatted = None
    t_complex_section = None
    t_complex_style = None
    t_complex_table = None
    t_complex_table_cell = None
    t_complex_table_row = None
    t_complex_tag = None

    token2name = {}
    _text = None

    @staticmethod
    def join_as_text(tokens):
        return "".join([x.text or "" for x in tokens])

    def _get_text(self):
        if self._text is None and self.source is not None:
            self._text = self.source[self.start: self.start + self.len]
        return self._text

    def _set_text(self, t):
        self._text = t

    text = property(_get_text, _set_text)

    def __init__(self, type=None, start=None, len=None,
                 source=None, text=None, **kw):
        self.type = type
        self.start = start
        self.len = len
        self.source = source
        if text is not None:
            self.text = text

        self.__dict__.update(kw)

    def __repr__(self):
        if isinstance(self, Token):
            r = [self.token2name.get(self.type, self.type)]
        else:
            r = [self.__class__.__name__]
        if self.text is not None:
            r.append(repr(self.text)[1:])
        if self.tagname:
            r.append(" tagname=")
            r.append(repr(self.tagname))
        if self.rawtagname:
            r.append(" rawtagname=")
            r.append(repr(self.rawtagname))

        if self.vlist:
            r.append(" vlist=")
            r.append(repr(self.vlist))
        if self.target:
            r.append(" target=")
            r.append(repr(self.target))
        if self.level:
            r.append(" level=")
            r.append(repr(self.level))
        if self.ns is not None:
            r.append(" ns=")
            r.append(repr(self.ns))
        if self.lineprefix is not None:
            r.append(" lineprefix=")
            r.append(self.lineprefix)
        if self.interwiki:
            r.append(" interwiki=")
            r.append(repr(self.interwiki))
        if self.langlink:
            r.append(" langlink=")
            r.append(repr(self.langlink))
        if self.type == self.t_complex_style:
            r.append(repr(self.caption))
        elif self.caption:
            r.append("->")
            r.append(repr(self.caption))

        return "".join(r)

    show = _Show()


token2name = Token.token2name
for d in dir(Token):
    if d.startswith("t_"):
        token2name[getattr(Token, d)] = d
del d, token2name


def _split_tag(txt):
    matched_tag = re.match(r" *(\w+)(.*)", txt, re.DOTALL)
    if matched_tag is None:
        raise ValueError("could not match tag name")
    name = matched_tag.group(1)
    values = matched_tag.group(2)
    return name, values


def _analyze_html_tag(tag):
    text = tag.text
    self_closing = False
    if text.startswith("</"):
        name = text[2:-1]
        is_end_token = True
    elif text.endswith("/>"):
        name = text[1:-2]
        self_closing = True
        is_end_token = False  # ???
    else:
        name = text[1:-1]
        is_end_token = False

    name, values = _split_tag(name)
    tag.vlist = parse_params(values)
    name = name.lower()

    if name == "br":
        is_end_token = False

    tag.rawtagname = name
    tag.tag_selfClosing = self_closing
    tag.tag_isEndToken = is_end_token
    if is_end_token:
        tag.type = tag.t_html_tag_end


def dump_tokens(text, tokens):
    for type, start, len in tokens:
        print(type, repr(text[start: start + len]))


def scan(text):
    text += "\0" * 32
    return _mwscan.scan(text)


class CompatScanner:
    allowed_tags = None

    def _init_allowed_tags(self):
        self.allowed_tags = set(
            """
abbr b big blockquote br center cite code del div em endfeed font h1 h2 h3
h4 h5 h6 hr i index inputbox ins kbd li ol p pages references rss s small span
startfeed strike strong sub sup caption table td th tr tt u ul var dl dt dd
""".split()
        )

    def __call__(self, text, uniquifier=None):
        if self.allowed_tags is None:
            self._init_allowed_tags()

        if isinstance(text, str):
            text = six.text_type(text)

        tokens = scan(text)

        res = []

        def g():
            return text[start: start + tlen]

        for type, start, tlen in tokens:
            if type == Token.t_begintable:
                txt = g()
                count = txt.count(":")
                if count:
                    res.append(Token(type=Token.t_colon,
                                     start=start, len=count, source=text))
                tlen -= count
                start += count

            token = Token(type=type, start=start, len=tlen, source=text)

            if type == Token.t_entity:
                token.text = resolve_entity(g())
                token.type = Token.t_text
                res.append(token)
            elif type == Token.t_html_tag:
                s = g()
                if uniquifier:
                    s = uniquifier.replace_uniq(s)
                    token.text = s
                _analyze_html_tag(token)
                tagname = token.rawtagname

                if tagname in self.allowed_tags:
                    res.append(token)
                else:
                    res.append(Token(type=Token.t_text, start=start,
                                     len=tlen, source=text))
            else:
                res.append(token)

        return res


compat_scan = CompatScanner()


def tokenize(input_arg, uniquifier=None):
    if not input_arg:
        raise ValueError("must specify input argument in tokenize")
    return compat_scan(input_arg, uniquifier=uniquifier)
