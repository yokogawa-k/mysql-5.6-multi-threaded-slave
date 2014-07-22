#!/usr/bin/env python
# -*- coding: utf-8; -*-
# github に上げるテキストのタイトルを抜き出して目次を作る
#  https://github.com/sonots/growthforecast-tuning/blob/master/toc.rb
# vi: set ts=4 sw=4 sts=0 et:

import os,sys,urllib

filename = sys.argv[1]
flag = 0
start = 1
for i in open(filename, 'r'):
    if start == 1:
        start = 0
        continue
    if i.startswith('```'):
        flag = flag ^ 1
    if flag == 1:
        continue
    if i.startswith('#'):
        s = i.split(None,1)
        level = len(s[0]) -1
        title = s[1].strip()
        uri   = urllib.quote(title.lower().replace(' ', '-').replace('.', ''))
        print("%s* [%s](#%s)" % (' ' * level * 2, title, uri))