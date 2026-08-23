.PHONY: install test dashboard example lint clean

install:
	pip install -r requirements.txt

test:
	python -m pytest tests/ -q

dashboard:
	streamlit run dashboard/app.py

example:
	python examples/qqq_analysis.py

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
