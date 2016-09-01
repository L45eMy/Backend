import pickle
import time
import base64
import zlib
import os
import re

from mongokit import Connection, ObjectId
from documents import Result, Run, App, AppStoreApp, Account
from static_analyzer.analysis import Analysis 

class Poster:

    def __init__(self, publisher, mark=True, limit=500):
        self.publisher = publisher
        self.mark = mark
        self.limit = limit
        self.db = Connection()
        self.db.register([Result, Run, App, AppStoreApp, Account])

    def post(self):
        runs = self._get_runs(self.limit)
        current = 0
        total = min(runs.count(), self.limit)

        for run in runs:
            runId = run['_id']
            staticResult = self._get_static_result(runId)
            if staticResult is None:
                print("Error: No static result found for runId %s, skipping" % runId)
                continue

            runtimeResult = self._get_runtime_result(runId)
            if runtimeResult is None:
                print("Error: No runtime result found for runId %s, skipping" % runId)
                continue

            a = self._unpack_static_result(staticResult)

            self._fix_infoplists(a)

            print "%d %%: %s" % (round(current / float(total) * 100), a.bundleid)

            runtimeData = runtimeResult.resultInfo.data

            for key, val in runtimeData.iteritems():
                a[key] = val

            requests = self._get_network_results(runId)
            files = self._get_file_results(runId)
            files = list(files.resultInfo.data)

            self._publish_result(run, a, requests, files)

            current += 1

    def _fix_infoplists(self, elem):
        for binary in elem.binaries:
            if 'branch_key' in binary['info_plist'] and isinstance(binary['info_plist']['branch_key'], str):
                binary['info_plist']['branch_key'] = {
                    'live': binary['info_plist']['branch_key'],
                    'test': binary['info_plist']['branch_key']
                }

    def _get_runs(self, limit):
        query = {
            'dioscope.date_published': None
        }

        return self.db.Run.find(query).limit(limit)

    def _get_static_result(self, runId):
        query = {
            '$and': [
                { 'resultInfo.type': 'dioscope_static' },
                { 'run.$id': ObjectId(runId) }
            ]
        }

        return self.db.Result.fetch_one(query)

    def _unpack_static_result(self, result):
        resultId = result['_id']
        resultType = result.resultInfo['type']
        document_name = '%s_%s' % (resultType, resultId)
        f = result.fs.get_last_version(document_name)
        data = f.read()
        f.close()
        a = pickle.loads(data)
        return a

    def _publish_result(self, run, a, requests, files, mark=None):
        a_id = self.publisher.publish(a, requests, files)
        
        if (mark is not None and mark) or (mark is None and self.mark):
            run['dioscope'] = {
                'date_published': time.time(),
                'es_analysis_id': a_id
            }

            run.save()

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
            raw = data['body']
            del data['body']
            data['body'] = { 'raw': raw }

            content_type = None
            content_encoding = None
            redefine_content_length = None
            is_protocol_buffers = False

            # Parse headers for encoding
            if "headers" in data:
                for key, val in data['headers'].iteritems():
                    if key.lower() == "content-type":
                        content_type = val
                    elif key.lower() == "content-encoding":
                        content_encoding = val
                    elif key.lower() == "x-codec-format":
                        is_protocol_buffers = val.lower() == "protocolbuffers"
                    elif key.lower() == "content-length" and "," in val:
                        redefine_content_length = key

            # Content-length seems to be comma separated sometimes, we redefine it with the first value
            if redefine_content_length is not None:
                old_content_length = data['headers'][redefine_content_length]
                new_content_length = re.search(r'\d+', old_content_length).group()
                data['headers'][redefine_content_length] = new_content_length

            if not is_protocol_buffers:
                if content_encoding is not None:
                    data['body']['blob'] = self._uncompress_data(raw, content_encoding)
                else:
                    data['body']['blob'] = data['body']['raw'] 

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
                    if mime_type in ["application/json", "application/x-amz-json-1.1", "application/x-www-form-urlencoded"] or mime_type.startswith("text/"):
                        text = base64.b64decode(data['body']['blob'])

                        # Ignore text with garbage
                        try:
                            text.decode(charset)
                            data['body']['text'] = text
                        except UnicodeError:
                            pass

                    # TODO: Multipart
                    # elif mime_type == "multipart/form-data":
                    #     Do the magic

        return data

    def _uncompress_data(self, data, encoding):
        # Save work if it's not compressed
        if encoding in ["identity", "amz-1.0"] or data is None:
            return data

        raw_data = base64.b64decode(data)
        uncompressed = None

        try:
            if encoding == "deflate":
                uncompressed = zlib.decompress(raw_data)
            elif encoding == "gzip":
                uncompressed = zlib.decompress(raw_data, 16+zlib.MAX_WBITS)
            elif encoding in ['rc4,gzip']:
                return None 
            else:
                raise Exception('Unknown encoding %s' % encoding)

            return base64.b64encode(uncompressed)
        except zlib.error:
            return None

    def _get_file_results(self, runId):
        query = {
            '$and': [
                { 'resultInfo.type': 'filelist' },
                { 'run.$id': ObjectId(runId) }
            ]
        }

        results = self.db.Result.fetch_one(query)

        return results
