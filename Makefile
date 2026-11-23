CACHE_DIR ?= .cache/fastembed
.PHONY: install test demo verify
install:
	python -m pip install -r requirements-all.txt
test:
	python -m unittest discover -s tests -v
demo:
	python -m docchat.web --library .docchat-library --ocr
verify:
	python eval/release_check.py --cache-dir $(CACHE_DIR)
