# -*- coding: utf-8 -*-

ESHOST = "localhost"
ESINDEX = "dioscope"
ESTIMEOUT = 300

from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import RequestError, NotFoundError, TransportError

class Publisher:
    
    def __init__(self, host, index, timeout=300):
        self.index = index
        print "Posting to Elasticsearch host %s…" % host
        self.es = Elasticsearch([host], timeout=timeout)

    def publish(self, a):
        print "Posting %s…" % a.bundleid

        self._create_or_update_itunesmeta(a)

        try:
            analysis_id = self._create_analysis_doc(a)

            for binary in a.binaries:
                binary_id = self._create_binary_doc(analysis_id, binary)

                if binary.classes is not None:
                    self._create_class_docs(binary_id, binary.classes)

        except (RequestError, TransportError) as err:
            print "Oops: %s %s %s" % (err.error, err.info, err.status_code)
            exit()

        return analysis_id

    def _create_or_update_itunesmeta(self, a):
        try:
            existing_app = self.es.get(index=ESINDEX, doc_type="app", id=a.bundleid)['_source']
        except NotFoundError:
            existing_app = None

        if (existing_app is not None) and a.itunes_meta.is_older_than(existing_app["currentVersionReleaseDate"]):
            app = existing_app
        else:
            app = a.itunes_meta
            self.es.index(index=ESINDEX, doc_type="app", id=a.bundleid, body=app)
            print "App did not exist or was outdated. Created/updated app doc."

    def _create_analysis_doc(self, a):
        es_analysis = self.es.index(index=self.index, doc_type="analysis", parent=a.bundleid, body=dict(a))
        return es_analysis['_id']

    def _create_binary_doc(self, analysis_id, binary):
        es_binary = self.es.index(index=self.index, doc_type="binary", parent=analysis_id, body=dict(binary))
        return es_binary['_id']

    def _create_class_docs(self, binary_id, classes):
        bulk_actions = []
        for objc_class in classes:
            bulk_actions.append({
                "_index": self.index,
                "_type": "class",
                "_parent": binary_id,
                "_source": dict(objc_class)
            })
        
        for success, info in helpers.parallel_bulk(self.es, bulk_actions):
            if not success:
                print "A class document failed: %s" % info