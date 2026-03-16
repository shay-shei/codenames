PORT ?= 8080

ve:
	uv venv --python 3.11 ve

server: ve
	source ./ve/bin/activate && gunicorn codenames:app --bind 0.0.0.0:$(PORT)

dev: ve
	source ./ve/bin/activate && FLASK_APP=codenames flask run --host=0.0.0.0 --port=8080 --reload --debug

