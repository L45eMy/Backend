import pickle
import time

from mongokit import Connection
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
            self._publish_result(result)

    def _get_results(self):
        query = {
            '$and': [
                { 'resultInfo.type': 'dioscope_static' },
                { 'dioscope.date_published': { '$exists': False } }
            ]
        }

        return self.db.Result.find(query)

    def _publish_result(self, result):
        resultId = result['_id']
        resultType = result.resultInfo['type']
        document_name = '%s_%s' % (resultType, resultId)
        f = result.fs.get_last_version(document_name)
        data = f.read()
        f.close()
        a = pickle.loads(data)

        a_id = self.publisher.publish(a)
        result['dioscope'] = {
            'date_published': time.time(),
            'es_analysis_id': a_id
        }
        result.save()