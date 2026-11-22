"""Day 8 real-model check: the library-aware web UI over HTTP, fully offline.

Uses the cached MiniLM embedder (no network) against the shipped synthetic
samples. Run from the repo root with the search dependencies installed:

    python eval/web_library_check.py --cache-dir /path/to/model/cache --offline

Writes eval/day08-results.json. Not a calibrated accuracy benchmark: two
synthetic documents, one machine, one process.
"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docchat.library import Library  # noqa: E402
from docchat.web import make_server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=120)
    conn.request(method, path, body=body)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data)


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

    with tempfile.TemporaryDirectory(prefix='docchat-web-lib-') as store:
        library = Library(store, cache_dir=args.cache_dir, offline=args.offline)
        server = make_server(0, library=library)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            status, add1 = request(port, 'POST', '/library/add', body=policy_bytes)
            results['policy_add'] = {'http': status, 'embedded': add1.get('embedded'),
                                     'chunks': add1.get('chunks')}
            status, add2 = request(port, 'POST', '/library/add', body=policy_bytes)
            results['policy_readd_uses_cache'] = (
                status == 200 and add2.get('embedded') is False)
            status, add3 = request(port, 'POST', '/library/add', body=receipt_bytes)
            results['scanned_receipt_add'] = {
                'http': status, 'chunks': add3.get('chunks'),
                'no_text_pages': add3.get('no_text_pages')}

            status, docs = request(port, 'GET', '/documents')
            results['documents_listed'] = sorted(d['source_sha256']
                                                 for d in docs['documents']) == \
                sorted([policy_sha, receipt_sha])

            question = 'What is the refund window for fees?'
            status, answer = request(port, 'POST',
                                     '/library/ask?q=' + question.replace(' ', '%20'))
            cited = answer.get('citations') or []
            results['cross_doc_ask'] = {
                'http': status, 'status': answer.get('status'),
                'documents': answer.get('documents'),
                'cited_correct_document': bool(cited) and
                    cited[0].get('source_sha256') == policy_sha,
                'cited_page': cited[0].get('page') if cited else None}

            absent = 'What is the warranty period for the lunar module?'
            status, answer2 = request(port, 'POST',
                                      '/library/ask?q=' + absent.replace(' ', '%20'))
            results['absent_question_abstained'] = (
                answer2.get('status') == 'insufficient_evidence'
                and not answer2.get('citations'))

            results['passed'] = all([
                results['policy_add']['http'] == 200,
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
        finally:
            server.shutdown()
            server.server_close()

    out = ROOT / 'eval' / 'day08-results.json'
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return 0 if results['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
