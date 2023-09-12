# Copyright (c) 2007-2009 PediaPress GmbH
# See README.rst for additional licensing information.

"""
The parse tree generated by the parser is a 1:1 representation of the mw-markup.
Unfortunately these trees have some flaws if used to generate derived documents.

This module seeks to rebuild the parstree
to be:
 * more logical markup
 * clean up the parse tree
 * make it more accessible
 * allow for validity checks
 * implement rebuilding strategies

Useful Documentation:
http://en.wikipedia.org/wiki/Wikipedia:Don%27t_use_line_breaks
http://meta.wikimedia.org/wiki/Help:Advanced_editing
http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext
"""


import copy
import re

import six

from mwlib.log import Log
from mwlib.parser import Math, Ref, Link, URL, NamedURL  # not used but imported
from mwlib.parser import CategoryLink, SpecialLink, Caption, LangLink  # not used but imported
from mwlib.parser import ArticleLink, InterwikiLink, NamespaceLink
from mwlib.parser import Item, ItemList, Node, Table, Row, Cell, Paragraph, PreFormatted
from mwlib.parser import Section, Style, TagNode, Text, Timeline
from mwlib.parser import ImageLink, Article, Book, Chapter

log = Log("advtree")


def _idIndex(lst, el):
    """Return index of first appeareance of element el in list lst"""

    for i, e in enumerate(lst):
        if e is el:
            return i
    raise ValueError("element %r not found" % el)


def debug(method):  # use as decorator
    def f(self, *args, **kargs):
        log(f"\n{method.__name__} called with {args!r} {kargs!r}")
        log(f"on {self!r} attrs:{self.attributes!r} style:{self.style!r}")
        p = self
        while p.parent:
            p = p.parent
            log("%r" % p)
        return method(self, *args, **kargs)

    return f


class AdvancedNode:
    """Mixin Class that extends Nodes so they become easier accessible.

    Allows to traverse the tree in any direction and
    build derived convinience functions
    """

    parent = None  # parent element
    is_block_node = False

    def copy(self):
        "return a copy of this node and all its children"
        p = self.parent
        try:
            self.parent = None
            n = copy.deepcopy(self)
        finally:
            self.parent = p
        return n

    def move_to(
        self, targetnode, prefix=False
    ):  # FIXME: bad name. rename to moveBehind, and create method moveBefore
        """Move this node behind the target node.

        If prefix is true, move before the target node.
        """

        if self.parent:
            self.parent.remove_child(self)
        tp = targetnode.parent
        idx = _idIndex(tp.children, targetnode)
        if not prefix:
            idx += 1
        tp.children.insert(idx, self)
        self.parent = tp

    def has_child(self, c):
        """Check if node c is child of self"""
        try:
            _idIndex(self.children, c)
            if not c.parent is self:
                raise ValueError("child not found")
            return True
        except ValueError:
            return False

    def append_child(self, c):
        self.children.append(c)
        c.parent = self

    def remove_child(self, c):
        self.replace_child(c, [])
        if c.parent is not None:
            raise ValueError("child not removed")

    def replace_child(self, c, newchildren=[]):
        """Remove child node c and replace with newchildren if given."""

        idx = _idIndex(self.children, c)
        self.children[idx : idx + 1] = newchildren

        c.parent = None
        if self.has_child(c):
            raise ValueError("child not removed")
        for nc in newchildren:
            nc.parent = self

    def get_parents(self):
        """Return list of parent nodes up to the root node.

        The returned list starts with the root node.
        """

        parents = []
        n = self.parent
        while n:
            parents.append(n)
            n = n.parent
        parents.reverse()
        return parents

    def get_parent(self):
        """Return the parent node"""
        return self.parent

    def get_level(self):
        """Returns the number of nodes of same class in parents"""
        return [p.__class__ for p in self.get_parents()].count(self.__class__)

    def get_parent_nodes_by_class(self, klass):  # FIXME: rename to getParentsByClass
        """returns parents w/ klass"""
        return [p for p in self.parents if p.__class__ == klass]

    def get_child_nodes_by_class(self, klass):  # FIXME: rename to getChildrenByClass
        """returns all children  w/ klass"""
        return [p for p in self.get_all_children() if p.__class__ == klass]

    def get_all_children(self):
        """don't confuse w/ Node.allchildren() which returns allchildren + self"""
        for c in self.children:
            yield c
            yield from c.get_all_children()

    def get_siblings(self):
        """Return all siblings WITHOUT self"""
        return [c for c in self.get_all_siblings() if c is not self]

    def get_all_siblings(self):
        """Return all siblings plus self"""
        if self.parent:
            return self.parent.children
        return []

    def get_previous(self):
        """Return previous sibling"""
        s = self.get_all_siblings()
        try:
            idx = _idIndex(s, self)
        except ValueError:
            return None
        if idx - 1 < 0:
            return None
        else:
            return s[idx - 1]

    def get_next(self):
        """Return next sibling"""
        s = self.get_all_siblings()
        try:
            idx = _idIndex(s, self)
        except ValueError:
            return None
        if idx + 1 >= len(s):
            return None
        else:
            return s[idx + 1]

    def get_last(self):  # FIXME might return self. is this intended?
        """Return last sibling"""
        s = self.get_all_siblings()
        if s:
            return s[-1]

    def get_first(self):  # FIXME might return self. is this intended?
        """Return first sibling"""
        s = self.get_all_siblings()
        if s:
            return s[0]

    def get_last_child(self):
        """Return last child of this node"""
        if self.children:
            return self.children[-1]

    def get_first_child(self):
        "Return first child of this node"
        if self.children:
            return self.children[0]

    def get_first_leaf(self, callerIsSelf=True):
        """Return 'first' child that has no children itself"""
        if self.children:
            if self.__class__ == Section:  # first kid of a section is its caption
                if len(self.children) == 1:
                    return None
                else:
                    return self.children[1].get_first_leaf(callerIsSelf=False)
            else:
                return self.children[0].get_first_leaf(callerIsSelf=False)
        else:
            if callerIsSelf:
                return None
            else:
                return self

    def get_last_leaf(self, callerIsSelf=True):
        """Return 'last' child that has no children itself"""
        if self.children:
            return self.children[-1].get_first_leaf(callerIsSelf=False)
        else:
            if callerIsSelf:
                return None
            else:
                return self

    def get_all_display_text(self, amap=None):
        "Return all text that is intended for display"
        text = []
        if not amap:
            amap = {
                Text: "caption",
                Link: "target",
                URL: "caption",
                Math: "caption",
                ImageLink: "caption",
                ArticleLink: "target",
                NamespaceLink: "target",
            }
        skip_on_children = [Link, NamespaceLink]
        for n in self.allchildren():
            access = amap.get(n.__class__, "")
            if access:
                if n.__class__ in skip_on_children and n.children:
                    continue
                text.append(getattr(n, access))
        alltext = [t for t in text if t]
        if alltext:
            return "".join(alltext)
        else:
            return ""

    def get_style(self):
        if not self.attributes:
            return {}
        else:
            return self.attributes.get("style", {})

    def _clean_attrs(self, attrs):
        def ensureInt(val, min_val=1):
            try:
                return max(min_val, int(val))
            except ValueError:
                return min_val

        def ensureUnicode(val):
            if isinstance(val, six.text_type):
                return val
            elif isinstance(val, str):
                return six.text_type(val, "utf-8")
            else:
                try:
                    return six.text_type(val)
                except BaseException:
                    return ""

        def ensureDict(val):
            if isinstance(val, dict):
                return val
            else:
                return {}

        for (key, value) in attrs.items():
            if key in ["colspan", "rowspan"]:
                attrs[key] = ensureInt(value, min_val=1)
            elif key == "style":
                attrs[key] = self._clean_attrs(ensureDict(value))
            else:
                attrs[key] = ensureUnicode(value)
        return attrs

    def get_attributes(self):
        """ Return dict with node attributes (e.g. class, style, colspan etc.)"""
        vlist = getattr(self, "vlist", None)
        if vlist is None:
            self.vlist = vlist = {}

        attrs = self._clean_attrs(vlist)
        return attrs

    def has_class_id(self, classIDs):
        _class = self.attributes.get("class", "").split(" ")
        _id = self.attributes.get("id", "")
        return any(classID in _class or classID == _id for classID in classIDs)

    def is_visible(self):
        """Return True if node is visble. Used to detect hidden elements."""
        if self.style.get("display", "").lower() == "none":
            return False
        if self.style.get("visibility", "").lower() == "hidden":
            return False
        return True

    style = property(get_style)
    attributes = property(get_attributes)
    visible = property(is_visible)

    parents = property(get_parents)
    next = property(get_next)
    previous = property(get_previous)
    siblings = property(get_siblings)
    last = property(get_last)
    first = property(get_first)
    lastchild = property(get_last_child)
    firstchild = property(get_first_child)


# --------------------------------------------------------------------------
# MixinClasses w/ special behaviour
# -------------------------------------------------------------------------


class AdvancedTable(AdvancedNode):
    @property
    def rows(self):
        return [r for r in self if r.__class__ == Row]

    @property
    def numcols(self):
        max_cols = 0
        for row in self.children:
            cols = sum(
                [
                    cell.attributes.get("colspan", 1)
                    for cell in row.children
                    if not getattr(cell, "colspanned", False)
                ]
            )
            max_cols = max(max_cols, cols)
        return max_cols


class AdvancedRow(AdvancedNode):
    @property
    def cells(self):
        return [c for c in self if c.__class__ == Cell]


class AdvancedCell(AdvancedNode):
    @property
    def colspan(self, attr="colspan"):
        """ colspan of cell. result is always non-zero, positive int"""
        return self.attributes.get("colspan") or 1

    @property
    def rowspan(self):
        """ rowspan of cell. result is always non-zero, positive int"""
        return self.attributes.get("rowspan") or 1


class AdvancedSection(AdvancedNode):
    def getSectionLevel(self):
        return 1 + self.get_level()


class AdvancedImageLink(AdvancedNode):
    is_block_node = property(lambda s: not s.isInline())

    @property
    def render_caption(self):
        explicit_caption = bool(getattr(self, "thumb") or getattr(self, "frame", "") == "frame")
        is_gallery = len(self.get_parent_nodes_by_class(Gallery)) > 0
        has_children = len(self.children) > 0
        return (explicit_caption or is_gallery) and has_children


class AdvancedMath(AdvancedNode):
    @property
    def is_block_node(self):
        if self.caption.strip().startswith("\\begin{align}") or self.caption.strip().startswith(
            "\\begin{alignat}"
        ):
            return True
        return False


# --------------------------------------------------------------------------
# Missing as Classes derived from parser.Style
# -------------------------------------------------------------------------


class Italic(Style, AdvancedNode):
    _tag = "i"


class Emphasized(Style, AdvancedNode):
    _tag = "em"


class Strong(Style, AdvancedNode):
    _tag = "strong"


class DefinitionList(Style, AdvancedNode):
    _tag = "dl"


class DefinitionTerm(Style, AdvancedNode):
    _tag = "dt"


class DefinitionDescription(Style, AdvancedNode):
    _tag = "dd"


class Blockquote(Style, AdvancedNode):
    "margins to left &  right"
    _tag = "blockquote"


class Indented(
    Style, AdvancedNode
):  # fixme: node is deprecated, now style node ':' always becomes a DefinitionDescription
    """margin to the left"""

    def getIndentLevel(self):
        return self.caption.count(":")

    indentlevel = property(getIndentLevel)


class Overline(Style, AdvancedNode):
    _style = "overline"


class Underline(Style, AdvancedNode):
    _style = "u"


class Sub(Style, AdvancedNode):
    _style = "sub"
    _tag = "sub"


class Sup(Style, AdvancedNode):
    _style = "sup"
    _tag = "sup"


class Small(Style, AdvancedNode):
    _style = "small"
    _tag = "small"


class Big(Style, AdvancedNode):
    _style = "big"
    _tag = "big"


class Cite(Style, AdvancedNode):
    _style = "cite"
    _tag = "cite"


class Var(Style, AdvancedNode):
    _tag = "var"
    _style = "var"


_styleNodeMap = {k._style: k for k in [Overline, Underline, Sub, Sup, Small, Big, Cite, Var]}

# --------------------------------------------------------------------------
# Missing as Classes derived from parser.TagNode
# http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext
# -------------------------------------------------------------------------


class Source(TagNode, AdvancedNode):
    _tag = "source"


class Code(TagNode, AdvancedNode):
    _tag = "code"


class BreakingReturn(TagNode, AdvancedNode):
    _tag = "br"


class HorizontalRule(TagNode, AdvancedNode):
    _tag = "hr"


class Index(TagNode, AdvancedNode):
    _tag = "index"


class Teletyped(TagNode, AdvancedNode):
    _tag = "tt"


class Reference(TagNode, AdvancedNode):
    _tag = "ref"


class ReferenceList(TagNode, AdvancedNode):
    _tag = "references"


class Gallery(TagNode, AdvancedNode):
    _tag = "gallery"


class Center(TagNode, AdvancedNode):
    _tag = "center"


class Div(TagNode, AdvancedNode):
    _tag = "div"


class Span(TagNode, AdvancedNode):  # span is defined as inline node which is in theory correct.
    _tag = "span"


class Font(TagNode, AdvancedNode):
    _tag = "font"


class Strike(TagNode, AdvancedNode):
    _tag = "strike"


# class S(TagNode, AdvancedNode):
#     _tag = "s"


class ImageMap(TagNode, AdvancedNode):  # defined as block node, maybe incorrect
    _tag = "imagemap"


class Ruby(TagNode, AdvancedNode):
    _tag = "ruby"


class RubyBase(TagNode, AdvancedNode):
    _tag = "rb"


class RubyParentheses(TagNode, AdvancedNode):
    _tag = "rp"


class RubyText(TagNode, AdvancedNode):
    _tag = "rt"


class Deleted(TagNode, AdvancedNode):
    _tag = "del"


class Inserted(TagNode, AdvancedNode):
    _tag = "ins"


class TableCaption(TagNode, AdvancedNode):
    _tag = "caption"


class Abbreviation(TagNode, AdvancedNode):
    _tag = "abbr"


_tagNodeMap = {
    k._tag: k
    for k in [
        Abbreviation,
        BreakingReturn,
        Center,
        Code,
        DefinitionDescription,
        DefinitionList,
        DefinitionTerm,
        Deleted,
        Div,
        Font,
        Gallery,
        HorizontalRule,
        ImageMap,
        Index,
        Inserted,
        Reference,
        ReferenceList,
        Ruby,
        RubyBase,
        RubyText,
        Source,
        Span,
        Strike,
        TableCaption,
        Teletyped,
    ]
}
_styleNodeMap["s"] = Strike  # Special Handling for deprecated s style
_tagNodeMap["kbd"] = Teletyped

# --------------------------------------------------------------------------
# BlockNode separation for AdvancedNode.is_block_node
# -------------------------------------------------------------------------

"""
For writers it is useful to know whether elements are inline (within a paragraph) or not.
We define list for blocknodes, which are used in AdvancedNode as:

AdvancedNode.is_block_node

Image depends on result of Image.isInline() see above

Open Issues: Math, Magic, (unknown) TagNode

"""
_blockNodes = (
    Article,
    Blockquote,
    Book,
    BreakingReturn,
    Cell,
    Center,
    Chapter,
    DefinitionDescription,
    DefinitionList,
    DefinitionTerm,
    Div,
    Gallery,
    HorizontalRule,
    ImageMap,
    Indented,
    Item,
    ItemList,
    Paragraph,
    PreFormatted,
    ReferenceList,
    Row,
    Section,
    Source,
    Table,
    Timeline,
)

for k in _blockNodes:
    k.is_block_node = True


# --------------------------------------------------------------------------
# funcs for extending the nodes
# -------------------------------------------------------------------------


def mix_in_class(pyClass, mixInClass, makeFirst=False):
    if mixInClass not in pyClass.__bases__:
        if makeFirst:
            pyClass.__bases__ = (mixInClass,) + pyClass.__bases__
        else:
            pyClass.__bases__ += (mixInClass,)


def extend_classes(node):
    for c in node.children[:]:
        extend_classes(c)
        c.parent = node


# Nodes we defined above and that are separetly handled in extendClasses
_advancedNodesMap = {
    Section: AdvancedSection,
    ImageLink: AdvancedImageLink,
    Math: AdvancedMath,
    Cell: AdvancedCell,
    Row: AdvancedRow,
    Table: AdvancedTable,
}
mix_in_class(Node, AdvancedNode)
for k, v in _advancedNodesMap.items():
    mix_in_class(k, v)

# --------------------------------------------------------------------------
# Functions for fixing the parse tree
# -------------------------------------------------------------------------


def fix_tag_nodes(node):
    """Detect known TagNodes and and transfrom to appropriate Nodes"""
    for c in node.children:
        if c.__class__ == TagNode:
            if c.caption in _tagNodeMap:
                c.__class__ = _tagNodeMap[c.caption]
            elif c.caption in ("h1", "h2", "h3", "h4", "h5", "h6"):  # FIXME
                # NEED TO MOVE NODE IF IT REALLY STARTS A SECTION
                c.__class__ = Section
                mix_in_class(c.__class__, AdvancedSection)
                c.level = int(c.caption[1])
                c.caption = ""
            else:
                log.warn("fixTagNodes, unknowntagnode %r" % c)
        fix_tag_nodes(c)


def fix_style_node(node):
    """
    parser.Style Nodes are mapped to logical markup
    detection of DefinitionList depends on removeNodes
    and removeNewlines
    """
    if node.__class__ != Style:
        return
    if node.caption == "''":
        node.__class__ = Emphasized
        node.caption = ""
    elif node.caption == "'''''":
        node.__class__ = Strong
        node.caption = ""
        em = Emphasized("''")
        for c in node.children:
            em.append_child(c)
        node.children = []
        node.append_child(em)
    elif node.caption == "'''":
        node.__class__ = Strong
        node.caption = ""
    elif node.caption == ";":
        node.__class__ = DefinitionTerm
        node.caption = ""
    elif node.caption.startswith(":"):
        node.__class__ = DefinitionDescription
        node.indentlevel = len(re.findall("^:+", node.caption)[0])
        node.caption = ""
    elif node.caption == "-":
        node.__class__ = Blockquote
        node.caption = ""
    elif node.caption in _styleNodeMap:
        node.__class__ = _styleNodeMap[node.caption]
        node.caption = ""
    else:
        log.warn("fixStyle, unknownstyle %r" % node)
        return node

    return node


def fix_style_nodes(node):
    if node.__class__ == Style:
        fix_style_node(node)
    for c in node.children[:]:
        fix_style_nodes(c)


def remove_nodes(node):
    """
    the parser generates empty Node elements that do
    nothing but group other nodes. we remove them here
    """
    if node.__class__ == Node and not (node.previous is None and node.parent.__class__ == Section):
        # first child of section groups heading text - grouping Node must not be removed
            node.parent.replace_child(node, node.children)

    for c in node.children[:]:
        remove_nodes(c)


def remove_newlines(node):
    """
    remove newlines, tabs, spaces if we are next to a blockNode
    """
    if node.__class__ in (PreFormatted, Source):
        return

    todo = [node]
    while todo:
        node = todo.pop()
        if node.__class__ is Text and node.caption:
            if not node.caption.strip():
                prev = node.previous or node.parent  # previous sibling node or parentnode
                next = node.next or node.parent.next
                if not next or next.is_block_node or not prev or prev.is_block_node:
                    node.parent.remove_child(node)
            node.caption = node.caption.replace("\n", " ")

        for c in node.children:
            if c.__class__ in (PreFormatted, Source):
                continue
            todo.append(c)


def build_advanced_tree(root):  # USE WITH CARE
    """
    extends and cleans parse trees
    do not use this funcs without knowing whether these
    Node modifications fit your problem
    """
    funs = [
        extend_classes,
        fix_tag_nodes,
        remove_nodes,
        remove_newlines,
        fix_style_nodes,
    ]
    for f in funs:
        f(root)


def _validate_parser_tree(node, parent=None):
    # helper to assert tree parent link consistency
    if parent is not None:
        _idIndex(parent.children, node)  # asserts it occures only once
    for c in node:
        _idIndex(node.children, c)  # asserts it occures only once
        if c not in node.children:
            raise ValueError(f"child {c!r} not in children of {node!r}")
        _validate_parser_tree(c, node)


def _validate_parents(node, parent=None):
    # helper to assert tree parent link consistency
    if parent is not None:
        if not parent.has_child(node):
            raise ValueError(f"parent {parent!r} has no child {node!r}")
    else:
        if node.parent is not None:
            raise ValueError(f"node {node!r} has parent {node.parent!r}")
    for c in node:
        if not node.has_child(c):
            raise ValueError(f"node {node!r} has no child {c!r}")
        _validate_parents(c, node)


def get_advanced_tree(fn):
    from mwlib.dummydb import DummyDB
    from mwlib.uparser import parse_string

    db = DummyDB()
    with open(fn) as f:
        tree_input = six.text_type(f.read(), "utf8")
    r = parse_string(title=fn, raw=tree_input, wikidb=db)
    build_advanced_tree(r)
    return r


def simpleparse(raw):  # !!! USE FOR DEBUGGING ONLY !!!
    import sys

    from mwlib import dummydb, parser
    from mwlib.uparser import parse_string

    input = raw.decode("utf8")
    r = parse_string(title="title", raw=input, wikidb=dummydb.DummyDB())
    build_advanced_tree(r)
    parser.show(sys.stdout, r, 0)
    return r
