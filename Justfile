set shell := ["zsh", "-cu"]

project_root := justfile_directory()
python := "python3"
pip := python + " -m pip"
unittest := python + " -m unittest discover -s tests -p 'test_*.py'"

# Show available tasks
_default:
  @just --list

# Install runtime dependencies
install:
  {{pip}} install -r requirements.txt

# Upgrade pip and install runtime dependencies
bootstrap:
  {{python}} -m pip install --upgrade pip
  {{pip}} install -r requirements.txt

# Run the menu bar app
run:
  {{python}} KCSApp.py

# Run the standard test suite
test:
  {{unittest}}

# Run a single unittest module, e.g. `just test-file tests.test_ui_render`
test-file module:
  {{python}} -m unittest {{module}}

# Byte-compile key source files for a quick syntax check
compile:
  {{python}} -m py_compile KCSApp.py coinpricebar/*.py coinpricebar/sources/*.py tests/*.py

# Build the macOS .app bundle with py2app
build:
  {{python}} setup.py py2app

# Remove common generated artifacts
clean:
  rm -rf build dist __pycache__ .pytest_cache
  find . -type d -name '__pycache__' -prune -exec rm -rf {} +

# Tail the application log
logs:
  tail -n 80 kucoin_status.log

# Open the UI config file in the default editor
open-config:
  {{python}} -c "from pathlib import Path; import webbrowser; path = Path('config.json').resolve(); path.write_text('{\\n  \"ui\": {}\\n}\\n', encoding='utf-8') if not path.exists() else None; webbrowser.open(path.as_uri())"

# Run install + tests as a quick local verification
check: install test
