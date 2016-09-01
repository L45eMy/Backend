# -*- coding: utf-8 -*-

from poster import Poster
from publisher import Publisher
import argparse

parser = argparse.ArgumentParser(description='Sends unpublished results from the local MongoDB to an Elasticsearch server.')
parser.add_argument('-s', '--host', metavar='<host>', default='localhost', help='define an Elasticsearch host (default: localhost)')
parser.add_argument('-i', '--index', metavar='<index>', default='dioscope', help='define an Elasticsearch index (default: dioscope)')
parser.add_argument('-n', '--no-mark', action='store_true', help='Do not mark sent runs as published (default: false)')
parser.add_argument('-l', "--limit", type=int, metavar='n', default='500', help='limit selected runs')

args = parser.parse_args()

publisher = Publisher(args.host, args.index)
poster = Poster(publisher, mark=(not args.no_mark), limit=args.limit)
poster.post()