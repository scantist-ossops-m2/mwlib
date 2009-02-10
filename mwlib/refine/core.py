#! /usr/bin/env python

import sys
from mwlib.utoken import tokenize, show, token as T, walknode
from mwlib.refine import util
from mwlib import namespace

from mwlib.refine.parse_table import parse_tables, parse_table_cells, parse_table_rows

try:
    from blist import blist
except ImportError:
    import warnings
    warnings.warn("using normal list. parsing might be slower. please run 'easy_install blist'")
    blist = list

T.t_complex_table = "complex_table"
T.t_complex_caption = "complex_caption"
T.t_complex_table_row = "complex_table_row"
T.t_complex_table_cell = "complex_table_cell"
T.t_complex_tag = "complex_tag"
T.t_complex_link = "link"
T.t_complex_section = "section"
T.t_complex_article = "article"
T.t_complex_indent = "indent"
T.t_complex_line = "line"
T.t_complex_named_url = "named_url"
T.t_complex_style = "style"
T.t_complex_node = "node"
T.t_vlist = "vlist"

T.children = None


def get_recursive_tag_parser(tagname, break_at=None):
    if break_at is None:
        break_at = lambda _: False
        
    def recursive_parse_tag(tokens, refined):            
        i = 0
        stack = []
        while i<len(tokens):
            t = tokens[i]
            if stack and break_at(t):
                start = stack.pop()
                sub = tokens[start+1:i]
                tokens[start:i] = [T(type=T.t_complex_tag, start=0, len=0, children=sub, tagname=tagname)]
                refined.append(tokens[start])
                i=start+1
            elif t.type==T.t_html_tag and t.tagname==tagname:
                if t.tag_selfClosing:
                    tokens[i].type = T.t_complex_tag
                else:
                    stack.append(i)
                i+=1
            elif t.type==T.t_html_tag_end and t.tagname==tagname:
                if stack:
                    start = stack.pop()
                    sub = tokens[start+1:i]
                    tokens[start:i+1] = [T(type=T.t_complex_tag, vlist=tokens[start].vlist, start=tokens[start].start, len=4, children=sub, tagname=tagname)]
                    refined.append(tokens[start])
                    i = start+1
                else:
                    i+=1
            else:
                i+= 1

        while stack:
            start = stack.pop()
            sub = tokens[start+1:]
            tokens[start:] = [T(type=T.t_complex_tag, start=tokens[start].start, len=4, children=sub, tagname=tagname)]
            refined.append(tokens[start])

        refined.append(tokens)
    recursive_parse_tag.__name__ += "_"+tagname
    
    return recursive_parse_tag

parse_div = get_recursive_tag_parser("div")

def _li_break_at(token):
    if token.type==T.t_html_tag and token.tagname=="li":
        return True
    return False
parse_source = get_recursive_tag_parser("source")

parse_li = get_recursive_tag_parser("li", _li_break_at)
parse_ol = get_recursive_tag_parser("ol")
parse_ul = get_recursive_tag_parser("ul")
parse_span = get_recursive_tag_parser("span")
parse_p = get_recursive_tag_parser("p")
parse_ref = get_recursive_tag_parser("ref")
parse_math = get_recursive_tag_parser("math")
parse_small = get_recursive_tag_parser("small")
parse_b = get_recursive_tag_parser("b")
parse_sup = get_recursive_tag_parser("sup")

class bunch(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)
        
class parse_sections(object):
    def __init__(self, tokens, refined):
        self.tokens = tokens
        self.refined = refined
        self.run()
        
    def run(self):
        tokens = self.tokens
        i = 0

        sections = []
        current = bunch(start=None, end=None, endtitle=None)

        def create():
            l1 = tokens[current.start].text.count("=")
            l2 = tokens[current.endtitle].text.count("=")
            level = min (l1, l2)
            # FIXME add = when l1!=l2
            
            caption = T(type=T.t_complex_caption, start=0, len=0, children=tokens[current.start+1:current.endtitle])
            sub = blist([caption])
            sub.extend(tokens[current.endtitle+1:i])
            sect = T(type=T.t_complex_section, start=0, len=0, children=sub, level=level)
            tokens[current.start:i] = [sect] 
            
            self.refined.append(tokens[current.start])

            while sections and level<sections[-1].level:
                sections.pop()
            if sections and level>sections[-1].level:
                sections[-1].children.append(tokens[current.start])
                del tokens[current.start]
                current.start -= 1

            sections.append(sect)
            
        while i<len(self.tokens):
            t = tokens[i]
            if t.type==T.t_section:
                if current.endtitle is not None:
                    create()                    
                    i = current.start+1
                    current = bunch(start=None, end=None, endtitle=None)
                else:
                    current.start = i
                    i += 1
            elif t.type==T.t_section_end:
                current.endtitle = i
                i+= 1
            else:
                i+=1

        if current.endtitle is not None:
            create()
        self.refined.append(tokens)

class parse_urls(object):
    def __init__(self, tokens, refined):
        self.tokens = tokens
        self.refined = refined
        self.run()
        
    def run(self):
        tokens = self.tokens
        i=0
        start = None
        while i<len(tokens):
            t = tokens[i]
            
            if t.type==T.t_urllink and start is None:
                start = i
                i+=1
            elif t.type==T.t_special and t.text=="]" and start is not None:
                sub = self.tokens[start+1:i]
                self.tokens[start:i+1] = [T(type=T.t_complex_named_url, children=sub, caption=self.tokens[start].text[1:])]
                self.refined.append(sub)
                i = start
                start = None
            else:
                i+=1
                
        self.refined.append(tokens)

class parse_singlequote(object):
    def __init__(self, tokens, refined):
        self.tokens = tokens
        self.refined = refined
        self.run()

    def run(self):
        def finish():
            assert len(counts)==len(styles)
            
            from mwlib.parser import styleanalyzer
            states = styleanalyzer.compute_path(counts)

            
            last_apocount = 0
            for i, s in enumerate(states):
                apos = "'"*(s.apocount-last_apocount)
                if apos:
                    styles[i].children.insert(0, T(type=T.t_text, text=apos))
                last_apocount = s.apocount

                if s.is_bold and s.is_italic:
                    styles[i].caption = "'''''"
                elif s.is_bold:
                    styles[i].caption = "'''"
                elif s.is_italic:
                    styles[i].caption = "''"
                else:
                    styles[i].type = T.t_complex_node
            
        
        tokens = self.tokens
        pos = 0
        start = None
        counts = []
        styles = []
        
        while pos<len(tokens):
            t = tokens[pos]
            if t.type==T.t_singlequote:
                if start is None:
                    counts.append(len(t.text))
                    start = pos
                    pos+=1
                else:
                    tokens[start:pos] = [T(type=T.t_complex_style, children=tokens[start+1:pos])]
                    styles.append(tokens[start])
                    pos = start+1
                    start = None
            elif t.type==T.t_newline:
                if start is not None:
                    tokens[start:pos] = [T(type=T.t_complex_style, children=tokens[start+1:pos])]
                    styles.append(tokens[start])
                    pos = start
                    start = None
                pos += 1
                
                if counts:
                    finish()
                    counts = []
                    styles = []
            else:
                pos += 1

        
        if start is not None:
            tokens[start:pos] = [T(type=T.t_complex_style, children=tokens[start+1:pos])]
            styles.append(tokens[start])
            
        if counts:
            finish()
                
                    
        
class parse_lines(object):
    def __init__(self, tokens, refined):
        self.tokens = tokens
        self.refined = refined
        self.run()

        
    def analyze(self, lines):

        def getchar(node):
            if node.lineprefix:
                return node.lineprefix[0]
            return None
        
        
        lines.append(T(type=T.t_complex_line, lineprefix='<guard>')) # guard

        
        startpos = 0
        while startpos<len(lines)-1:
            prefix = getchar(lines[startpos])
            if prefix is None:
                startpos += 1
                continue
            
            i = startpos+1
            while getchar(lines[i])==prefix:
                i+=1

            
            sub = lines[startpos:i]
            for x in sub:
                if x.lineprefix:
                    x.lineprefix = x.lineprefix[1:]
            self.analyze(sub)


            def makelist():
                for idx, x in enumerate(sub):
                    if x.type==T.t_complex_line:
                        x.type=T.t_complex_tag
                        x.tagname = "li"
                        self.refined.append(x.children)
                    else:
                        sub[idx] = T(type=T.t_complex_tag, tagname="li", children=sub[idx:idx+1])                        
                        self.refined.append(sub[idx].children)
                        
            if prefix==':':
                node = T(type=T.t_complex_indent, start=0, len=0, children=sub)
                self.refined.append(sub)
            elif prefix=='*':
                makelist()
                node = T(type=T.t_complex_tag, start=0, len=0, children=sub, tagname="ul")
            elif prefix=="#":
                makelist()
                node = T(type=T.t_complex_tag, start=0, len=0, children=sub, tagname="ol")
            elif prefix==';':
                self.refined.append(sub)
                node = T(type=T.t_complex_bold, start=0, len=0, children=sub)
            else:
                assert 0
                
            lines[startpos:i] = [node]
            startpos += 1


        del lines[-1] # remove guard
        
    def run(self):
        tokens = self.tokens
        i = 0
        lines = []
        startline = None
        firsttoken = None
                                   
        while i<len(self.tokens):
            t = tokens[i]
            if t.type in (T.t_item, T.t_colon):
                if firsttoken is None:
                    firsttoken = i
                startline = i
                i+=1
            elif t.type==T.t_newline and startline is not None:
                sub = self.tokens[startline+1:i+1]
                lines.append(T(type=T.t_complex_line, start=tokens[startline].start, len=0, children=sub, lineprefix=tokens[startline].text))
                startline = None
                i+=1
            elif t.type==T.t_break:
                if startline is not None:
                    sub = self.tokens[startline+1:i]
                    lines.append(T(type=T.t_complex_line, start=tokens[startline].start, len=0, children=sub, lineprefix=tokens[startline].text))
                    startline=None
                if lines:
                    self.analyze(lines)
                    self.tokens[firsttoken:i] = lines
                    i = firsttoken
                    firsttoken=None
                    lines=[]
                    continue
                    
                firsttoken = None
                
                lines = []
                i+=1
            else:
                if startline is None and lines:
                    self.analyze(lines)
                    self.tokens[firsttoken:i] = lines
                    i = firsttoken
                    starttoken=None
                    lines=[]
                    firsttoken=None
                else:
                    i+=1

        if startline is not None:
            sub = self.tokens[startline+1:]
            lines.append(T(type=T.t_complex_line, start=tokens[startline].start, len=0, children=sub, lineprefix=tokens[startline].text))

        if lines:
            self.analyze(lines)
            self.tokens[firsttoken:] = lines                

        self.refined.append(tokens)
        
class parse_links(object):
    def __init__(self, tokens, refined):
        self.tokens = tokens
        self.refined = refined
        self.run()

    def handle_image_modifier(self, mod, node):
        mod = mod.strip().lower()
        if mod=='thumb' or mod=='thumbnail':
            node.thumb = True
            return True
        
        if mod in ('left', 'right', 'center', 'none'):
            node.align = mod
            return True
        
        if mod in ('frame', 'framed', 'enframed', 'frameless'):
            node.frame = mod
            return True
        
        if mod=='border':
            node.border = True
            return True

        if mod.startswith('print='):
            node.printargs = mod[len('print='):]

        if mod.startswith('alt='):
            node.alt = mod[len('alt='):]

        if mod.startswith('link='):
            node.link = mod[len('link='):]

        if mod.endswith('px'):
                # x200px
                # 100x200px
                # 200px
                mod = mod[:-2]
                width, height = (mod.split('x')+['0'])[:2]
                try:
                    width = int(width)
                except ValueError:
                    width = 0

                try:
                    height = int(height)
                except ValueError:
                    height = 0

                node.width = width
                node.height = height
                return True
        return False
    
    def extract_image_modifiers(self, marks, node):
        cap = None
        for i in range(1,len(marks)-1):
            tmp = self.tokens[marks[i]+1:marks[i+1]]
            if not self.handle_image_modifier(T.join_as_text(tmp), node):
                cap = tmp
        return cap
        
        
    def run(self):
        tokens = self.tokens
        i = 0
        marks = []

        stack = []
        
        
        while i<len(self.tokens):
            t = tokens[i]
            if t.type==T.t_2box_open:
                if len(marks)>1:
                    stack.append(marks)
                marks = [i]
                i+=1
            elif t.type==T.t_special and t.text=="|":
                marks.append(i)
                i+=1
            elif t.type==T.t_2box_close and marks:
                marks.append(i)
                start = marks[0]
                
                target = T.join_as_text(tokens[start+1:marks[1]]).strip()
                if target.startswith(":"):
                    target = target[1:]
                    colon = True
                else:
                    colon = False
                    
                if not target:
                    i+=1
                    if stack:
                        marks=stack.pop()
                    else:
                        marks=[]                        
                    continue
                else:
                    # FIXME: parse image modifiers: thumb, frame, ...
                    ns, partial, full = namespace.splitname(target)

                    
                    if ns==namespace.NS_MAIN:
                        # FIXME: could be an interwiki/language link. -> set ns=None
                        pass
                    
                    node = T(type=T.t_complex_link, start=0, len=0, children=blist(), ns=ns, colon=colon)

                    sub = None
                    if ns==namespace.NS_IMAGE:
                        sub = self.extract_image_modifiers(marks, node)                        
                    elif len(marks)>2:
                        sub = tokens[marks[1]+1:marks[-1]]

                    if sub is None:
                        sub = [T(type=T.t_text, start=0, len=0, text=target)]
                        
                    node.children = sub
                    tokens[start:i+1] = [node]
                    node.target = target
                    self.refined.append(sub)
                    if stack:
                        marks = stack.pop()
                    else:
                        marks = []
                    i = start+1
            else:
                i+=1

        self.refined.append(tokens)
        

            
def parse_txt(txt):
    tokens = blist(tokenize(txt))

    refine = [tokens]
    parsers = [parse_singlequote, parse_urls, parse_small, parse_sup, parse_b, parse_lines, parse_source, parse_math, parse_ref, parse_span, parse_li, parse_p, parse_ul, parse_ol, parse_links, parse_sections, parse_div, parse_tables]
    while parsers:
        p = parsers.pop()
        #print "doing", p, "on:", refine
        
        next = []
        
        for x in refine:
            if isinstance(x, (list, blist, tuple)):
                toks = x
            else:
                toks = x.children
            #print "BEFORE:", p, toks
            p(toks, next)
            #print "AFTER:", toks

        refine = next
        
    return tokens