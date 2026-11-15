import argparse
import sys
import time
from .client import image_question, ChatError


def main():
    parser = argparse.ArgumentParser(description='Ask a local vision model about a PNG/JPEG. PDFs are not supported yet.')
    parser.add_argument('image')
    parser.add_argument('question')
    parser.add_argument('--model', default='qwen2.5vl:7b')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    started = time.perf_counter()
    try:
        answer = image_question(args.image, args.question, model=args.model, timeout=args.timeout)
    except (ChatError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(answer)
    print(f'End-to-end request: {time.perf_counter() - started:.2f}s (includes model loading if cold)', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
