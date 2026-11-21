"""Real-model multi-document check on the synthetic samples. Tiny, not a benchmark.
Run from repo root: python eval/library_check.py --cache-dir PATH --offline
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docchat.library import Library
from docchat.search import MODEL

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cache-dir')
parser.add_argument('--offline', action='store_true')
args = parser.parse_args()

with tempfile.TemporaryDirectory(prefix='docchat-libe-') as tmp:
    lib = Library(Path(tmp) / 'store', cache_dir=args.cache_dir, offline=args.offline)
    policy = lib.add_bytes((root / 'samples/policy.pdf').read_bytes())
    receipt = lib.add_bytes((root / 'samples/scanned-receipt.pdf').read_bytes())
    again = lib.add_bytes((root / 'samples/policy.pdf').read_bytes())
    answered = lib.ask('How long do I have to ask for my money back?')
    absent = lib.ask("What is the CEO's birthday?")
    result = {
        'model': MODEL,
        'policy': {'sha': policy['source_sha256'], 'chunks': policy['chunks'],
                   'embedded_first': policy['embedded'],
                   'reused_on_readd': not again['embedded']},
        'scanned_receipt': {'sha': receipt['source_sha256'],
                            'chunks': receipt['chunks'],
                            'no_text_pages': receipt['no_text_pages']},
        'answered': {'status': answered['status'],
                     'cited_sha': (answered['citations'][0]['source_sha256']
                                   if answered['citations'] else None),
                     'cited_page': (answered['citations'][0]['page']
                                    if answered['citations'] else None),
                     'ok': (answered['status'] == 'answered'
                            and answered['citations']
                            and answered['citations'][0]['source_sha256'] == policy['source_sha256']
                            and answered['citations'][0]['page'] == 2)},
        'absent': {'status': absent['status'],
                   'ok': absent['status'] == 'insufficient_evidence'},
        'limit': 'Two synthetic sample documents only; proves plumbing and provenance, not general accuracy. Threshold fixture-tuned.'}
print(json.dumps(result, indent=2))
