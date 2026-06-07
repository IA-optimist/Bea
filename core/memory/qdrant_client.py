import os
QDRANT_URL = os.environ.get('QDRANT_URL', 'http://qdrant:6333')
QDRANT_API_KEY = os.environ.get('QDRANT_API_KEY', '')
COLLECTIONS = {
    'beamax_memory_384': {'size': 384, 'distance': 'Cosine'},
    'bea_continual_memory': {'size': 768, 'distance': 'Cosine'},
    'beamax_knowledge': {'size': 768, 'distance': 'Cosine'},
}

class QdrantWrapper:
    def __init__(self, url=QDRANT_URL, api_key=QDRANT_API_KEY):
        self.url = url.rstrip('/')
        self.headers = {'Content-Type': 'application/json'}
        if api_key:
            self.headers['api-key'] = api_key
        self._session = None

    def _sess(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(self.headers)
        return self._session

    def health(self):
        try:
            r = self._sess().get(f'{self.url}/healthz', timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_collection(self, collection, size=768):
        try:
            cfg = COLLECTIONS.get(collection, {'size': size, 'distance': 'Cosine'})
            r = self._sess().put(f'{self.url}/collections/{collection}',
                json={'vectors': {'size': cfg['size'], 'distance': cfg['distance']}}, timeout=10)
            return r.status_code in (200, 409)
        except Exception:
            return False

    def upsert(self, collection, point_id, vector, payload):
        try:
            _id = abs(hash(point_id)) % (2**53)
            r = self._sess().put(f'{self.url}/collections/{collection}/points',
                json={'points': [{'id': _id, 'vector': vector, 'payload': payload}]}, timeout=15)
            r.raise_for_status()
            return True
        except Exception:
            return False

    def search(self, collection, vector, limit=5, score_threshold=0.3, filter_dict=None):
        try:
            body = {'vector': vector, 'limit': limit, 'score_threshold': score_threshold, 'with_payload': True}
            if filter_dict:
                body['filter'] = filter_dict
            r = self._sess().post(f'{self.url}/collections/{collection}/points/search', json=body, timeout=10)
            r.raise_for_status()
            return [{'id': h['id'], 'score': h['score'], 'payload': h.get('payload', {})} for h in r.json().get('result', [])]
        except Exception:
            return []

    def delete(self, collection, point_id):
        try:
            _id = abs(hash(point_id)) % (2**53)
            r = self._sess().post(f'{self.url}/collections/{collection}/points/delete', json={'points': [_id]}, timeout=10)
            r.raise_for_status(); return True
        except Exception:
            return False

    def count(self, collection):
        try:
            r = self._sess().get(f'{self.url}/collections/{collection}', timeout=5)
            return r.json().get('result', {}).get('points_count', 0)
        except Exception:
            return -1

_client = None
def get_qdrant():
    global _client
    if _client is None:
        _client = QdrantWrapper()
    return _client
