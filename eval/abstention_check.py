"""Gate check on the tiny synthetic set. Fixture-tuned, not calibration.
Run from repo root: python eval/abstention_check.py --cache-dir PATH --offline
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docchat.pdf import read_pdf, chunk_pages
from docchat.search import Index, LocalEmbedder, MODEL
from docchat.answer import build_answer, DEFAULT_MIN_SCORE

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cache-dir')
parser.add_argument('--offline', action='store_true')
args = parser.parse_args()
source = root / 'samples/policy.pdf'
cases = json.loads((root / 'eval/retrieval_cases.json').read_text())
index = Index(chunk_pages(read_pdf(source), size=500, overlap=75),
              LocalEmbedder(args.cache_dir, args.offline))
digest = hashlib.sha256(source.read_bytes()).hexdigest()
results = []
for case in cases:
    matches = index.search(case['question'], k=3)
    answer = build_answer(case['question'], matches, digest, DEFAULT_MIN_SCORE)
    if case['page'] is None:
        ok = answer['status'] == 'insufficient_evidence'
    else:
        ok = (answer['status'] == 'answered' and answer['citations']
              and answer['citations'][0]['page'] == case['page'])
    results.append({**case, 'status': answer['status'],
                    'top_score': round(matches[0].score, 6), 'ok': ok})
answerable = [r for r in results if r['page'] is not None]
absent = [r for r in results if r['page'] is None]
print(json.dumps({'model': MODEL, 'source_sha256': digest,
                  'min_score': DEFAULT_MIN_SCORE,
                  'answered_ok': sum(r['ok'] for r in answerable),
                  'answerable': len(answerable),
                  'abstained_ok': sum(r['ok'] for r in absent),
                  'absent': len(absent), 'results': results,
                  'limit': 'Threshold tuned on these 8 synthetic questions over 2 pages; scores are not calibrated confidence and other corpora need retuning. Extractive quotes only; no generated-answer quality measured.'},
                 indent=2))
