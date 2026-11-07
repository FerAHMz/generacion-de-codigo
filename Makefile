# Compiscript — Análisis semántico, código intermedio y generación de MIPS
# Uso local (requiere Java y el runtime de Python):
#   make venv      -> crea .venv e instala dependencias
#   make mars      -> descarga el simulador MARS 4.5 en tools/
#   make grammar   -> genera lexer/parser/visitor en compiscript/generated
#   make test      -> corre la batería de tests
#   make run F=... -> analiza un archivo .cps
#   make ide       -> levanta el IDE web en http://localhost:8080 (o make ide PORT=9999)
# Uso con Docker (mismo entorno del curso):
#   make docker-build && make docker-shell

ANTLR_JAR := antlr-4.13.1-complete.jar
GRAMMAR   := program/Compiscript.g4
GEN_DIR   := compiscript/generated
PY        := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
F         ?= program/program.cps
PORT      ?= 8080
MARS_JAR  := tools/Mars4_5.jar
MARS_URL  := https://github.com/dpetersanderson/MARS/releases/download/v.4.5.1/Mars4_5.jar

.PHONY: venv mars grammar test run ide clean docker-build docker-shell

venv:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

mars: $(MARS_JAR)

$(MARS_JAR):
	mkdir -p tools
	curl -fsSL -o $(MARS_JAR) $(MARS_URL)

grammar:
	java -jar $(ANTLR_JAR) -Dlanguage=Python3 -visitor -no-listener \
		-Xexact-output-dir -o $(GEN_DIR) $(GRAMMAR)

test:
	$(PY) -m pytest -q

run:
	$(PY) Driver.py $(F)

ide:
	PORT=$(PORT) $(PY) -m ide.app

clean:
	rm -rf $(GEN_DIR)/*.py $(GEN_DIR)/*.interp $(GEN_DIR)/*.tokens .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

docker-build:
	docker build --rm . -t csp-image

docker-shell:
	docker run --rm -ti -p $(PORT):$(PORT) -e PORT=$(PORT) -v "$$(pwd)":/app csp-image
