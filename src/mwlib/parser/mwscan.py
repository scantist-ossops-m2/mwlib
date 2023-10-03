#! /usr/bin/env python

# Copyright (c) 2007-2009 PediaPress GmbH
# See README.txt for additional licensing information.

import re
import sys

import _mwscan
import htmlentitydefs

from mwlib.parser import paramrx


class Token:
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
    t_begin_table = 10
    t_end_table = 11
    t_html_tag = 12
    t_singlequote = 13
    t_pre = 14
    t_section = 15
    t_section_end = 16
    t_item = 17
    t_colon = 18
    t_semicolon = 19
    t_hrule = 20
    t_newline = 21
    t_column = 22
    t_row = 23
    t_tablecaption = 24
    t_urllink = 25

    token2name = {}


for directory in dir(Token):
    token2name = Token.token2name
    if directory.startswith("t_"):
        token2name[getattr(Token, directory)] = directory
else:
    del directory


def _split_tag(txt):
    matched_tag = re.match(r" *(\w+)(.*)", txt)
    if matched_tag is None:
        raise ValueError("could not match tag name")
    name = matched_tag.group(1)
    values = matched_tag.group(2)
    return name, values


def dump_tokens(text, tokens):
    for token_type, start, length in tokens:
        print(token_type, repr(text[start: start + length]))


def scan(text):
    text += "\0" * 32
    tokens = _mwscan.scan(text)
    return ScanResult(text, tokens)


def resolve_entity(entity):
    if entity[1] == "#":
        try:
            if entity[2] == "x" or entity[2] == "X":
                return chr(int(entity[3:-1], 16))
            return chr(int(entity[2:-1]))
        except ValueError:
            return entity
    else:
        try:
            return chr(htmlentitydefs.name2codepoint[entity[1:-1]])
        except KeyError:
            return entity


class ScanResult:
    def __init__(self, source, toks):
        self.source = source
        self.toks = toks

    def rawtext(self, token):
        (_, start, tlen) = token
        return self.source[start: start + tlen]

    def text(self, token):
        raw_text = self.rawtext(token)
        if token[0] == Token.t_entity:
            return resolve_entity(raw_text)
        return raw_text

    def dump(self, out=None):
        if out is None:
            out = sys.stdout
        for token in self:
            out.write("%s\n" % self.repr(token))

    def repr(self, token):
        return f"({Token.token2name.get(token[0])}, {self.rawtext(token)!r})"

    def __len__(self):
        return len(self.toks)

    def __iter__(self):
        return iter(self.toks)

    def __getitem__(self, idx):
        return self.toks[idx]


class _CompatScanner:
    from mwlib.tagext import default_registry as tagextensions

    allowed_tags = None

    class Ignore:
        pass

    tok2compat = {
        Token.t_text: "TEXT",
        Token.t_special: "SPECIAL",
        Token.t_2box_open: "[[",
        Token.t_2box_close: "]]",
        Token.t_http_url: "URL",
        Token.t_break: "BREAK",
        Token.t_singlequote: "SINGLEQUOTE",
        Token.t_pre: "PRE",
        Token.t_section: "SECTION",
        Token.t_section_end: "ENDSECTION",
        Token.t_magicword: Ignore,
        Token.t_comment: Ignore,
        Token.t_end: Ignore,
        Token.t_item: "ITEM",
        Token.t_colon: "EOLSTYLE",
        Token.t_semicolon: "EOLSTYLE",
        Token.t_newline: "\n",
        Token.t_begin_table: "BEGINTABLE",
        Token.t_end_table: "ENDTABLE",
        Token.t_column: "COLUMN",
        Token.t_row: "ROW",
        Token.t_tablecaption: "TABLECAPTION",
        Token.t_urllink: "URLLINK",
    }

    def _init_allowed_tags(self):
        from mwlib.parser import _get_tags

        self.allowed_tags = _get_tags()

    def get_substring(self, text, start, tlen):
        return text[start: start + tlen]

    def append_to_result(self, res, token_type, text, start, tlen):
        return res.append((token_type, self.get_substring(text, start, tlen)))

    def _process_html_token_and_check_for_tag_match(self, tokens, iterator, text_start, text, tagname):
        should_break = False
        token_type, start, tlen = tokens[iterator]
        if text_start is None:
            text_start = start
        if token_type == Token.t_html_tag:
            tag_token = self.tagtoken(self.get_substring(text, start, tlen))
            if tag_token.t == tagname:
                should_break = True
                end_token = (tag_token, self.get_substring(text, start, tlen))
        text_end = start + tlen
        iterator += 1
        return should_break, iterator, text_start, text_end, end_token

    def _process_tag_and_extract_text(self, tokens, i, text_start, text, tag_token, closing_or_self_closing, res, substr, numtokens):
        should_continue = False
        if closing_or_self_closing:
            i += 1
            should_continue = True
        tagname = tag_token.t
        res.append((tag_token, substr))
        i += 1
        text_start = None
        text_end = None
        end_token = None
        while i < numtokens:
            should_break, i, text_start, text_end, end_token = self._process_html_token_and_check_for_tag_match(tokens, i, text_start, text, tagname)
            if should_break:
                break
        if text_end:
            res.append(("TEXT", text[text_start:text_end]))
        if end_token:
            res.append(end_token)
        return i, should_continue

    def _handle_nowiki_tag_and_append_text(self, i, is_end_token, tag_token, text, tokens, res, numtokens, scanres):
        i += 1
        if is_end_token or tag_token.self_closing:
            return i, True
        while i < numtokens:
            token_type, start, tlen = tokens[i]
            if token_type == Token.t_html_tag:
                tag_token = self.tagtoken(self.get_substring(text, start, tlen))
                if tag_token.t == "nowiki":
                    break
            res.append(("TEXT", scanres.text((token_type,
                                              start, tlen))))
            i += 1
        return i

    def _append_allowed_tag_or_text(self, tag_token, res, substr):
        if tag_token.t in self.allowed_tags:
            res.append((tag_token, substr))
        else:
            res.append(("TEXT", substr))

    def _append_table_start_or_end_token(self, is_end_token, res, text, start, tlen):
        if is_end_token:
            res.append(("ENDTABLE", self.get_substring(text, start, tlen)))
        else:
            res.append(("BEGINTABLE", self.get_substring(text, start, tlen)))

    def _process_and_classify_html_tags(self, tokens, i, start, tlen, text, res, numtokens, scanres):
        should_continue = False
        substr = self.get_substring(text, start, tlen)
        tag_token = self.tagtoken(substr)
        is_end_token = isinstance(tag_token, EndTagToken)
        closing_or_self_closing = is_end_token or tag_token.self_closing
        if tag_token.t in self.tagextensions or tag_token.t in ("imagemap", "gallery"):
            i, should_continue = self._process_tag_and_extract_text(tokens, i, None, text, tag_token, closing_or_self_closing, res, substr, numtokens)
            if should_continue:
                return i, True
        elif tag_token.t == "nowiki":
            i = self._handle_nowiki_tag_and_append_text(i, is_end_token, tag_token, text, tokens, res, numtokens, scanres)
        elif tag_token.t == "table":
            self._append_table_start_or_end_token(is_end_token, res, text, start, tlen)
        elif tag_token.t in ["th", "td"]:
            if not is_end_token:
                res.append(("COLUMN", self.get_substring(text, start, tlen)))
        elif tag_token.t == "tr":
            if not is_end_token:
                res.append(("ROW", self.get_substring(text, start, tlen)))
        else:
            self._append_allowed_tag_or_text(tag_token, res, substr)
        return i, False

    def __call__(self, text):
        if self.allowed_tags is None:
            self._init_allowed_tags()

        tokens = scan(text)
        scanres = ScanResult(text, tokens)

        res = []

        ignore = self.ignore
        tok2compat = self.tok2compat

        i = 0
        numtokens = len(tokens)
        while i < numtokens:
            token_type, start, tlen = tokens[i]
            compat = tok2compat.get(token_type)
            if compat is ignore:
                i += 1
                continue
            elif compat is not None:
                self.append_to_result(res, compat, text, start, tlen)
            elif token_type == Token.t_entity:
                res.append(("TEXT", resolve_entity(self.get_substring(text, start, tlen))))
            elif token_type == Token.t_hrule:
                res.append((self.tagtoken("<hr />"), self.get_substring(text, start, tlen)))
            elif token_type == Token.t_html_tag:
                i, should_continue = self._process_and_classify_html_tags(tokens, i, start, tlen, text, res, numtokens, scanres)
                if should_continue:
                    continue
            else:
                self.append_to_result(res, type, text, start, tlen)
            i += 1

        return res

    def tagtoken(self, text):
        self_closing = False
        if text.startswith("</"):
            name = text[2:-1]
            klass = EndTagToken
        elif text.endswith("/>"):
            name = text[1:-2]
            klass = TagToken
            self_closing = True
        else:
            name = text[1:-1]
            klass = TagToken

        name, values = _split_tag(name)

        values = dict(paramrx.findall(values))
        name = name.lower()

        if name in ['br', 'references']:
            klass = TagToken

        result = klass(name, text)
        result.self_closing = self_closing
        result.values = values
        return result


compat_scan = _CompatScanner()


class _BaseTagToken:
    def __eq__(self, other):
        if isinstance(other, str):
            return self.token == other
        if isinstance(other, self.__class__):
            return self.token == other.token
        return False

    def __ne__(self, other):
        return self != other

    def __hash__(self):
        return hash(self.token)


class TagToken(_BaseTagToken):
    values = {}
    self_closing = False

    def __init__(self, token, text=""):
        self.token = token
        self.text = text

    def __repr__(self):
        return f"<Tag:{self.token!r} {self.text!r}>"


class EndTagToken(_BaseTagToken):
    def __init__(self, token, text=""):
        self.token = token
        self.text = text

    def __repr__(self):
        return f"<EndTag:{self.token!r}>"


def tokenize(token_input):
    if token_input is None:
        raise ValueError("must specify input argument in tokenize")
    return compat_scan(token_input)
