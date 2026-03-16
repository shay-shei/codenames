PORT ?= 8080

ve:
	uv venv --python 3.11 ve
	source ./ve/bin/activate && uv pip install -r requirements.txt

server: ve
	source ./ve/bin/activate && gunicorn codenames:app --bind 0.0.0.0:$(PORT) --worker-class uvicorn.workers.UvicornWorker

dev: ve
	source ./ve/bin/activate && uvicorn codenames:app --host 0.0.0.0 --port 8080 --reload
