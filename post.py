# -*- coding: utf-8 -*-

from poster import Poster
from publisher import Publisher

ESHOST = "localhost"
ESINDEX = "dioscope"

publisher = Publisher(ESHOST, ESINDEX)
poster = Poster(publisher)
poster.post()