"""Day 9 real-model check: the FastAPI library API, fully offline.

Runs the actual ASGI app in-process (httpx TestClient transport) against a
real Library with the cached MiniLM embedder; no network. Same two synthetic
documents as the other evals, one machine, one process. Run from repo root:

    python eval/api_check.py --cache-dir /path/to/model/cache --offline

Writes eval/day09-results.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from docchat.api import create_app  # noqa: E402
from docchat.library import Library  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-dir')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()

    results = {}
    policy_bytes = (ROOT / 'samples' / 'policy.pdf').read_bytes()
    receipt_bytes = (ROOT / 'samples' / 'scanned-receipt.pdf').read_bytes()
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()

    with tempfile.TemporaryDirectory(prefix='docchat-api-') as store:
        library = Library(store, cache_dir=args.cache_dir, offline=args.offline)
        client = TestClient(create_app(library))

        response = client.post('/documents', content=policy_bytes)
        add1 = response.json()
        results['policy_add'] = {'http': response.status_code,
                                 'embedded': add1.get('embedded'),
                                 'chunks': add1.get('chunks')}
        response = client.post('/documents', content=policy_bytes)
        results['policy_readd_uses_cache'] = (
            response.status_code == 201
            and response.json().get('embedded') is False)
        response = client.post('/documents', content=receipt_bytes)
        add3 = response.json()
        results['scanned_receipt_add'] = {
            'http': response.status_code, 'chunks': add3.get('chunks'),
            'no_text_pages': add3.get('no_text_pages')}

        response = client.get('/documents')
        results['documents_listed'] = sorted(
            d['source_sha256'] for d in response.json()['documents']) == \
            sorted([policy_sha, receipt_sha])

        response = client.post(
            '/ask', json={'question': 'What is the refund window for fees?'})
        answer = response.json()
        cited = answer.get('citations') or []
        results['cross_doc_ask'] = {
            'http': response.status_code, 'status': answer.get('status'),
            'documents': answer.get('documents'),
            'cited_correct_document': bool(cited) and
                cited[0].get('source_sha256') == policy_sha,
            'cited_page': cited[0].get('page') if cited else None}

        response = client.post('/ask', json={
            'question': 'What is the warranty period for the lunar module?'})
        answer2 = response.json()
        results['absent_question_abstained'] = (
            answer2.get('status') == 'insufficient_evidence'
            and not answer2.get('citations'))

        results['passed'] = all([
            results['policy_add']['http'] == 201,
            results['policy_add']['embedded'] is True,
            results['policy_readd_uses_cache'],
            results['scanned_receipt_add']['chunks'] == 0,
            results['scanned_receipt_add']['no_text_pages'] == [1],
            results['documents_listed'],
            results['cross_doc_ask']['status'] == 'answered',
            results['cross_doc_ask']['cited_correct_document'],
            results['cross_doc_ask']['cited_page'] == 2,
            results['absent_question_abstained'],
        ])

    out = ROOT / 'eval' / 'day09-results.json'
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return 0 if results['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
