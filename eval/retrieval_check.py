"""Small synthetic check, not a general retrieval benchmark.
Run from repo root: python eval/retrieval_check.py --cache-dir PATH --offline
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docchat.pdf import read_pdf, chunk_pages
from docchat.search import Index, LocalEmbedder, MODEL

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cache-dir')
parser.add_argument('--offline', action='store_true')
args = parser.parse_args()
source = root / 'samples/policy.pdf'
cases = json.loads((root / 'eval/retrieval_cases.json').read_text())
index = Index(chunk_pages(read_pdf(source), size=500, overlap=75), LocalEmbedder(args.cache_dir,args.offline))
results=[]
for case in cases:
    match=index.search(case['question'],k=1)[0]
    results.append({**case, 'top_page': match.page, 'score': round(match.score,6),
                    'hit': match.page==case['page'] if case['page'] is not None else None})
answerable=[r for r in results if r['page'] is not None]
print(json.dumps({'model':MODEL,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'top1_page_hits':sum(r['hit'] for r in answerable),
                  'answerable_questions':len(answerable), 'results':results,
                  'limit':'Synthetic two-page sample only. No answer generation or calibrated abstention.'},indent=2))
