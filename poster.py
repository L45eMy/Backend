import pickle
import time
import base64
import zlib

from mongokit import Connection, ObjectId
from documents import Result, Run, App, AppStoreApp, Account
from static_analyzer.analysis import Analysis 


class Poster:

    def __init__(self, publisher):
        self.publisher = publisher
        self.db = Connection()
        self.db.register([Result, Run, App, AppStoreApp, Account])

    def post(self):
        results = self._get_results()
        for result in results:
            runId = result.run['_id']

            a = self._unpack_static_result(result)

            runtimeResult = self._get_runtime_result(runId)
            if runtimeResult is None:
                print "Error: No runtime result found for runId %s, skipping" % runId
                continue

            runtimeData = runtimeResult.resultInfo.data

            for key, val in runtimeData.iteritems():
                a[key] = val

            requests = self._get_network_results(runId)
            files = self._get_file_results(runId)
            files = list(files.resultInfo.data)

            self._publish_result(result, a, requests, files, mark=False)

    def _get_results(self):
        query = {
            '$and': [
                { 'resultInfo.type': 'dioscope_static' },
                { 'dioscope.date_published': None }
            ]
        }

        return self.db.Result.find(query)

    def _unpack_static_result(self, result):
        resultId = result['_id']
        resultType = result.resultInfo['type']
        document_name = '%s_%s' % (resultType, resultId)
        f = result.fs.get_last_version(document_name)
        data = f.read()
        f.close()
        a = pickle.loads(data)
        return a

    def _publish_result(self, result, a, requests, files, mark=True):
        a_id = self.publisher.publish(a, requests, files)

        if mark:
            result['dioscope'] = {
                'date_published': time.time(),
                'es_analysis_id': a_id
            }

            result.save()

    def _get_runtime_result(self, runId):
        query = {
            '$and': [
                { 'resultInfo.type': 'dioscope_runtime' },
                { 'run.$id': ObjectId(runId) }
            ]
        }
        
        return self.db.Result.fetch_one(query)

    def _get_network_results(self, runId):
        query = {
            '$and': [
                { 'resultInfo.type': 'network_request' },
                { 'run.$id': ObjectId(runId) }
            ]
        }

        results = self.db.Result.find(query)

        requests = []

        for result in results:
            requests.append(self._parse_network_result(result))

        return requests

    def _parse_network_result(self, result):
        data = dict(result.resultInfo.data)
        
        if "body" in data:
            body = data['body']
            del data['body']

            save_raw = False

            # Uncompress data
            content_type = None
            if "headers" in data:
                for key, val in data['headers'].iteritems():
                    if key.lower() == "content-type":
                        content_type = val
                    elif key.lower() == "content-encoding":
                        body = self._uncompress_data(body, val)
                    elif key.lower() == "x-codec-format":
                        save_raw = val.lower() == "protocolbuffers"

            if content_type is not None:
                content_type_data = content_type.partition(";")
                mime_type = content_type_data[0]
                content_type_components = content_type_data[2].strip().split(";")
                content_headers = {}

                if len(content_type_components[0]) > 0:
                    for content_type_component in content_type_components:
                        parts = content_type_component.split("=")
                        (key, val) = parts
                        key = key.strip()
                        val = val.strip()
                        content_headers[key] = val

                charset = 'utf-8'
                if 'charset' in content_headers:
                    charset = content_headers['charset']
                
                # Convert to text if mime type allows it
                if not save_raw and mime_type in ["application/json", "application/x-amz-json-1.1", "application/x-www-form-urlencoded"] or mime_type.startswith("text/"):
                    data['body'] = base64.b64decode(body.encode(charset))
                # TODO: Multipart
                # elif mime_type == "multipart/form-data":
                #     Do the magic

            data['blob'] = body

        return data

    def _uncompress_data(self, data, encoding):
        # Save work if it's not compressed
        if encoding in ["identity", "amz-1.0"] or data is None:
            return data

        raw_data = base64.b64decode(data)
        uncompressed = None

        if encoding == "deflate":
            uncompressed = zlib.decompress(raw_data)
        elif encoding == "gzip":
            uncompressed = zlib.decompress(raw_data, 16+zlib.MAX_WBITS)
        else:
            print data
            raise Exception("Unknown encoding %s" % encoding)

        return base64.b64encode(uncompressed)

    def _get_file_results(self, runId):
        query = {
            '$and': [
                { 'resultInfo.type': 'filelist' },
                { 'run.$id': ObjectId(runId) }
            ]
        }

        results = self.db.Result.fetch_one(query)

        return results
