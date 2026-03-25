PORT ?= 8080
VENV_NAME ?= ve

$(VENV_NAME):
	uv venv --python 3.11 $(VENV_NAME)

.PHONY: requirements
requirements: $(VENV_NAME)
	source ./$(VENV_NAME)/bin/activate && uv pip install -r requirements.txt

.PHONY: server
server: requirements
	source ./$(VENV_NAME)/bin/activate && gunicorn codenames:app --bind 0.0.0.0:$(PORT) --worker-class uvicorn.workers.UvicornWorker

.PHONY: dev
dev: requirements
	source ./$(VENV_NAME)/bin/activate && uvicorn codenames:app --host 0.0.0.0 --port 8080 --reload

.PHONY: format
format:
	@make .format VENV_NAME=.format
	source .format/bin/activate && uv pip install black && python -m black codenames