#! /usr/bin/env python

# Copyright (c) 2007, PediaPress GmbH
# See README.rst for additional licensing information.


import contextlib
import math

from .advtree import URL, Cell, ImageLink, Link, Math, NamedURL, Reference, Text


def getNodeHeight(node, params):
    line_height = params["lineHeight"]
    chars_per_line = params["charsPerLine"]
    paragraph_margin = params["paragraphMargin"]
    img_height = params["imgHeight"]

    height = 0
    non_follow_nodes = [Reference, NamedURL]
    amap = {
        Text: "caption",
        Link: "target",
        URL: "caption",
        Math: "caption",
        NamedURL: "caption",
    }
    access = amap.get(node.__class__, "")
    if access:
        txt = "" if node.__class__ == Link and node.children else getattr(node, access)
        if txt:
            # 40 chars per line --> number of lines --> 20pt height per line
            add_height = math.ceil(len(txt) / chars_per_line) * line_height
            if node.is_block_node:
                add_height += paragraph_margin
            else:
                # for inline nodes we reduce the height guess.
                # below that is compensated
                # for blocknode-heights w/o text
                add_height = add_height / 2
            height += add_height
    elif node.__class__ == ImageLink:
        if (
            node.is_inline()
        ):  # image heights are just wild guesses. in case of normal image, we assume 5 lines of text in height
            height += 0  # lineHeight
        else:
            height += line_height * img_height
    elif node.is_block_node:  # compensation for e.g. listItems which contain text.
        height += 0.5 * line_height

    for n in node.children[:]:
        if n.__class__ not in non_follow_nodes:
            height += getNodeHeight(n, params)
    return height


def splitRow(row, params):
    max_cell_height = params["maxCellHeight"]
    newrows = []
    cols = [[] for i in range(len(row.children))]
    for colindex, cell in enumerate(row.children):
        cell_height = 0
        items = []
        for item in cell.children:
            cell_height += getNodeHeight(item, params)
            if not items or cell_height < max_cell_height:
                items.append(item)
            else:
                cols[colindex].append(items)
                items = [item]
                cell_height = 0
        if items:
            cols[colindex].append(items)

    max_new_rows = max([len(col) for col in cols])

    for rowindex in range(max_new_rows):
        newrow = row.copy()
        newrow.children = []
        for colindex in range(len(cols)):
            try:
                cellchildren = cols[colindex][rowindex]
            except IndexError:
                cellchildren = []  # fixme maybe some better empty child
            cell = Cell()
            with contextlib.suppress(BaseException):
                cell.vlist = row.children[colindex].vlist

            for child in cellchildren:
                cell.appendChild(child)
            newrow.append_child(cell)
            newrow.suppress_bottom_border = True
        newrows.append(newrow)

    return newrows
