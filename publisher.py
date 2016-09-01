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

    def publish(self, a, requests, files):
        # print "Posting %s…" % a.bundleid

        self._create_or_update_itunesmeta(a)

        routing = a.bundleid

        try:
            analysis_id = self._create_analysis_doc(routing, a)

            for binary in a.binaries:
                binary_id = self._create_binary_doc(routing, analysis_id, binary)

                if binary.classes is not None:
                    self._create_class_docs(routing, binary_id, binary.classes)

            self._create_request_docs(routing, analysis_id, requests)
            self._create_file_docs(routing, analysis_id, files)

        except (RequestError, TransportError) as err:
            raise Exception("Oops: %s %s %s" % (err.error, err.info, err.status_code))

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
            print "%s did not exist or was outdated. Created/updated app doc." % a.bundleid

    def _create_analysis_doc(self, routing, a):
        es_analysis = self.es.index(index=self.index, doc_type="analysis", parent=a.bundleid, routing=routing, body=dict(a))
        return es_analysis['_id']

    def _create_binary_doc(self, routing, analysis_id, binary):
        es_binary = self.es.index(index=self.index, doc_type="binary", parent=analysis_id, routing=routing, body=dict(binary))
        return es_binary['_id']

    def _create_class_docs(self, routing, binary_id, classes):
        bulk_actions = []
        for objc_class in classes:
            bulk_actions.append({
                "_index": self.index,
                "_type": "class",
                "_parent": binary_id,
                "_routing": routing,
                "_source": dict(objc_class)
            })
        
        for success, info in helpers.parallel_bulk(self.es, bulk_actions):
            if not success:
                raise Exception("A class document failed: %s" % info)

    def _create_request_docs(self, routing, analysis_id, requests):
        bulk_actions = []
        for request in requests:
            bulk_actions.append({
                "_index": self.index,
                "_type": "network_request",
                "_parent": analysis_id,
                "_routing": routing,
                "_source": dict(request)
            })
        
        for success, info in helpers.parallel_bulk(self.es, bulk_actions):
            if not success:
                raise Exception( "A network_request document failed: %s" % info)

    def _create_file_docs(self, routing, analysis_id, files):
        bulk_actions = []
        for a_file in files:
            bulk_actions.append({
                "_index": self.index,
                "_type": "file_access",
                "_parent": analysis_id,
                "_routing": routing,
                "_source": dict(a_file)
            })
        
        for success, info in helpers.parallel_bulk(self.es, bulk_actions):
            if not success:
                raise Exception("A file_access document failed: %s" % info)