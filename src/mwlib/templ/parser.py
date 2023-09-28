# Copyright (c) 2007-2009 PediaPress GmbH
# See README.md for additional licensing information.


import re
from hashlib import sha256 as digest

import six

from mwlib import lrucache
from mwlib.templ.marks import eqmark
from mwlib.templ.nodes import IfNode, Node, SwitchNode, Template, Variable
from mwlib.templ.scanner import Symbols, tokenize


class AliasMap:
    def __init__(self, siteinfo):
        _map = {}
        _name2aliases = {}

        for magic_word_data in siteinfo.get("magicwords", []):
            name = magic_word_data["name"]
            aliases = magic_word_data["aliases"]
            _name2aliases[name] = aliases
            hashname = "#" + name
            for alias in aliases:
                _map[alias] = name
                _map["#" + alias] = hashname

        self._map = _map
        self._name2aliases = _name2aliases

    def resolve_magic_alias(self, name):
        if name.startswith("#"):
            resolved_name = self._map.get(name[1:])
            if resolved_name:
                return "#" + resolved_name
        else:
            return self._map.get(name)

    def get_aliases(self, name):
        return self._name2aliases.get(name) or []


def optimize(node):
    if type(node) is tuple:
        return tuple(optimize(x) for x in node)

    if isinstance(node, six.string_types):
        return node

    if len(node) == 1 and type(node) in (list, Node):
        return optimize(node[0])

    if isinstance(node, Node):  # (Variable, Template, IfNode)):
        return node.__class__(tuple(optimize(x) for x in node))
    else:
        # combine strings
        res = []
        tmp = []
        for optimized_node in (optimize(child_node) for child_node in node):
            if isinstance(optimized_node, six.string_types) and optimized_node is not eqmark:
                tmp.append(optimized_node)
            else:
                if tmp:
                    res.append("".join(tmp))
                    tmp = []
                res.append(optimized_node)
        if tmp:
            res.append("".join(tmp))

        node[:] = res

    if len(node) == 1 and type(node) in (list, Node):
        return optimize(node[0])

    if isinstance(node, list):
        return tuple(node)

    return node


class Parser:
    use_cache = False
    _cache = lrucache.MTLRUCache(2000)

    def __init__(self, txt, included=True, replace_tags=None, siteinfo=None):
        if isinstance(txt, str):
            txt = six.text_type(txt)

        self.txt = txt
        self.included = included
        self.replace_tags = replace_tags
        if siteinfo is None:
            from mwlib.siteinfo import get_siteinfo

            siteinfo = get_siteinfo("en")
        self.siteinfo = siteinfo
        self.name2rx = {"if": re.compile("^#if:"),
                        "switch": re.compile("^#switch:")}

        magicwords = self.siteinfo.get("magicwords", [])
        for magic_word_data in magicwords:
            name = magic_word_data["name"]
            if name in ("if", "switch"):
                aliases = [re.escape(alias) for alias in magic_word_data["aliases"]]
                regex_pattern = "^#({}):".format("|".join(aliases))
                self.name2rx[name] = re.compile(regex_pattern)

        self.aliasmap = AliasMap(self.siteinfo)

    def get_token(self):
        return self.tokens[self.pos]

    def set_token(self, tok):
        self.tokens[self.pos] = tok

    def variable_from_children(self, children):
        variable_components = []

        try:
            idx = children.index("|")
        except ValueError:
            variable_components.append(children)
        else:
            variable_components.append(children[:idx])
            variable_components.append(children[idx + 1:])

        return Variable(variable_components)

    def _consume_closing_braces(self, num):
        token_type, txt = self.get_token()
        if token_type != Symbols.bra_close or len(txt) < num:
            raise ValueError("expected closing braces")
        newlen = len(txt) - num
        if newlen == 0:
            self.pos += 1
            return

        if newlen == 1:
            token_type = Symbols.txt

        txt = txt[:newlen]
        self.set_token((token_type, txt))

    def _strip_ws(self, cond):
        if isinstance(cond, six.text_type):
            return cond.strip()

        cond = list(cond)
        if cond and isinstance(cond[0], six.text_type) and not cond[0].strip():
            del cond[0]

        if cond and isinstance(cond[-1],
                               six.text_type) and not cond[-1].strip():
            del cond[-1]
        cond = tuple(cond)
        return cond

    def switch_node_from_children(self, children):
        children[0] = children[0].split(":", 1)[1]
        args = self._parse_args(children)
        value = optimize(args[0])
        value = self._strip_ws(value)
        return SwitchNode((value, tuple(args[1:])))

    def if_node_from_children(self, children):
        children[0] = children[0].split(":", 1)[1]
        args = self._parse_args(children)
        cond = optimize(args[0])
        cond = self._strip_ws(cond)

        args[0] = cond
        node = IfNode(tuple(args))
        return node

    def magic_node_from_children(self, children, klass):
        children[0] = children[0].split(":", 1)[1]
        args = self._parse_args(children)
        return klass(args)

    def _parse_args(self, children, append_arg=False):
        args = []
        arg = []

        linkcount = 0
        for child in children:
            if child == "[[":
                linkcount += 1
            elif child == "]]":
                if linkcount:
                    linkcount -= 1
            elif child == "|" and linkcount == 0:
                args.append(arg)
                arg = []
                append_arg = True
                continue
            elif child == "=" and linkcount == 0:
                arg.append(eqmark)
                continue
            arg.append(child)

        if append_arg or arg:
            args.append(arg)

        return [optimize(arg) for arg in args]

    def _is_good_name(self, node):
        # we stop here on the first colon. this is wrong but we don't have
        # the list of allowed magic functions here...
        done = False
        if isinstance(node, six.string_types):
            node = [node]

        for child in node:
            if not isinstance(child, six.string_types):
                continue
            if ":" in child:
                child = child.split(":")[0]
                done = True

            if "[" in child or "]" in child:
                return False
            if done:
                break
        return True

    def template_from_children(self, children):
        if children and isinstance(children[0], six.text_type):
            stripped_lower_text = children[0].strip().lower()
            if self.name2rx["if"].match(stripped_lower_text):
                return self.if_node_from_children(children)
            if self.name2rx["switch"].match(stripped_lower_text):
                return self.switch_node_from_children(children)

            if ":" in stripped_lower_text:
                from mwlib.templ import magic_nodes

                name, _ = stripped_lower_text.split(":", 1)
                name = self.aliasmap.resolve_magic_alias(name) or name
                if name in magic_nodes.registry:
                    return self.magic_node_from_children(
                        children, magic_nodes.registry[name]
                    )

        # find the name
        name = []
        append_arg = False
        idx = 0
        for idx, c in enumerate(children):
            if c == "|":
                append_arg = True
                break
            name.append(c)

        name = optimize(name)
        if isinstance(name, six.text_type):
            name = name.strip()

        if not self._is_good_name(name):
            return Node(["{{"] + children + ["}}"])

        args = self._parse_args(children[idx + 1:], append_arg=append_arg)

        return Template([name, tuple(args)])

    def parse_open_brace(self):
        token_type, txt = self.get_token()
        n = []

        numbraces = len(txt)
        self.pos += 1

        linkcount = 0

        while 1:
            token_type, txt = self.get_token()

            if token_type == Symbols.bra_open:
                n.append(self.parse_open_brace())
            elif token_type is None:
                break
            elif token_type == Symbols.bra_close and linkcount == 0:
                closelen = len(txt)
                if closelen == 2 or numbraces == 2:
                    t = self.template_from_children(n)
                    n = []
                    n.append(t)
                    self._consume_closing_braces(2)
                    numbraces -= 2
                else:
                    v = self.variable_from_children(n)
                    n = []
                    n.append(v)
                    self._consume_closing_braces(3)
                    numbraces -= 3

                if numbraces < 2:
                    break
            elif token_type == Symbols.noi:
                self.pos += 1  # ignore <noinclude>
            else:  # link, txt
                if txt == "[[":
                    linkcount += 1
                elif txt == "]]" and linkcount > 0:
                    linkcount -= 1

                n.append(txt)
                self.pos += 1

        if numbraces:
            n.insert(0, "{" * numbraces)

        return n

    def parse(self):
        if self.use_cache:
            fp = digest(self.txt.encode("utf-8")).digest()
            try:
                return self._cache[fp]
            except KeyError:
                pass

        self.tokens = tokenize(
            self.txt, included=self.included, replace_tags=self.replace_tags
        )
        self.pos = 0
        n = []

        while 1:
            ty, txt = self.get_token()
            if ty == Symbols.bra_open:
                n.append(self.parse_open_brace())
            elif ty is None:
                break
            elif ty == Symbols.noi:
                self.pos += 1  # ignore <noinclude>
            else:  # bra_close, link, txt
                n.append(txt)
                self.pos += 1

        n = optimize(n)

        if self.use_cache:
            self._cache[fp] = n

        return n


def parse(txt, included=True, replace_tags=None, siteinfo=None):
    return Parser(
        txt, included=included, replace_tags=replace_tags, siteinfo=siteinfo
    ).parse()
