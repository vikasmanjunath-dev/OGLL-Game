.PHONY: help install run classic test smoke shots clean

PY ?= python3

help:
	@echo "make install   install runtime + dev dependencies"
	@echo "make run       play the game (Premium renderer)"
	@echo "make classic   play with the fixed-function (syllabus) renderer"
	@echo "make test      unit tests (no display needed)"
	@echo "make smoke     end-to-end test through every screen (needs OpenGL; uses xvfb-run on headless Linux)"
	@echo "make shots     regenerate the screenshots in docs/"
	@echo "make clean     remove caches and per-user files"

install:
	$(PY) -m pip install -r requirements-dev.txt

run:
	$(PY) lumen_drift.py

classic:
	$(PY) lumen_drift.py --classic

test:
	SDL_VIDEODRIVER=dummy $(PY) -m pytest tests -q --ignore=tests/test_smoke.py

smoke:
	@if command -v xvfb-run >/dev/null 2>&1 && [ -z "$$DISPLAY" ]; then xvfb-run -a $(PY) tests/test_smoke.py; else $(PY) tests/test_smoke.py; fi

shots:
	@if command -v xvfb-run >/dev/null 2>&1 && [ -z "$$DISPLAY" ]; then xvfb-run -a $(PY) scripts/make_screenshots.py; else $(PY) scripts/make_screenshots.py; fi

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache build dist *.egg-info shots lumen_shot_*.png lumen_drift_save.json lumen_drift_settings.json
