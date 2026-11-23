"""Release acceptance: real OCR + embeddings through API, no hosted inference."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from docchat.api import create_app
from docchat.library import Library

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-dir')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as store:
        lib = Library(store, cache_dir=args.cache_dir, offline=True, ocr=True)
        client = TestClient(create_app(lib))
        checks = {}
        for name in ['policy.pdf', 'scanned-receipt.pdf']:
            response = client.post('/documents', content=(ROOT / 'samples' / name).read_bytes())
            checks[name] = response.status_code == 201
        data = (ROOT / 'samples/scanned-receipt.pdf').read_bytes()
        result = client.post('/ask', json={'question': 'What is the total on the receipt?'}).json()
        citations = result.get('citations', [])
        checks['ocr_receipt_cited'] = (result.get('status') == 'answered' and
            'TOTAL: INR 180' in result.get('excerpt', '') and bool(citations) and
            citations[0]['page'] == 1 and citations[0]['source_sha256'] == hashlib.sha256(data).hexdigest())
        # A new instance loads stored vectors and answers after a restart.
        fresh = TestClient(create_app(Library(store, cache_dir=args.cache_dir, offline=True)))
        result = fresh.post('/ask', json={'question': 'What is the refund window for fees?'}).json()
        checks['restart_policy_cited'] = result.get('status') == 'answered' and result['citations'][0]['page'] == 2
        result = fresh.post('/ask', json={'question': 'What is the warranty period for the lunar module?'}).json()
        checks['absent_abstained'] = result.get('status') == 'insufficient_evidence'
        checks['bad_upload_rejected'] = client.post('/documents', content=b'not pdf').status_code == 422
        checks['cache_reused'] = client.post('/documents', content=data).json()['embedded'] is False
        checks['ocr_metadata'] = any(d.get('ocr_pages') == [1] for d in lib.documents())
        passed = all(checks.values())
        output = {'fixture_only': True, 'checks': checks, 'passed': passed,
                  'limits': 'Two synthetic PDFs, English printed OCR, fixture-tuned threshold; no general accuracy, GPU, chat or load-test claim.'}
        (ROOT / 'eval/release-results.json').write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps(output, indent=2))
        return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
