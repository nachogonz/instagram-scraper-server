.PHONY: help install dev test clean run stop lint format setup

# Default target
help:
	@echo "Instagram Scraper - Available commands:"
	@echo ""
	@echo "  make setup      - Initial setup (create venv, install deps)"
	@echo "  make install    - Install dependencies"
	@echo "  make dev        - Run development server"
	@echo "  make test       - Run example script with test account"
	@echo "  make run        - Run production server"
	@echo "  make stop       - Stop running server"
	@echo "  make clean      - Clean up cache and session files"
	@echo "  make lint       - Check code with linter"
	@echo "  make format     - Format code"
	@echo "  make shell       - Open Python shell with app context"
	@echo ""

# Variables
PYTHON := python3
VENV := .venv
VENV_BIN := $(VENV)/bin
PIP := $(VENV_BIN)/pip
PYTHON_VENV := $(VENV_BIN)/python

# Setup virtual environment and install dependencies
setup:
	@echo "🔧 Setting up development environment..."
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
	fi
	@echo "Installing dependencies..."
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@if [ ! -f .env ]; then \
		echo "Creating .env file from .env.example..."; \
		cp .env.example .env 2>/dev/null || echo "Please create .env file manually"; \
	fi
	@echo "✅ Setup complete!"
	@echo "📝 Don't forget to edit .env with your Instagram credentials"

# Install dependencies
install:
	@echo "📦 Installing dependencies..."
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "✅ Dependencies installed"

# Run development server
dev:
	@echo "🚀 Starting development server..."
	@if [ -f .env ]; then \
		ACCOUNT=$$(grep "^INSTAGRAM_USERNAME=" .env | cut -d'=' -f2 | tr -d '"' | tr -d "'"); \
		if [ -n "$$ACCOUNT" ]; then \
			echo ""; \
			echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
			echo "  👤  ACTIVE ACCOUNT: \033[1;33m$$ACCOUNT\033[0m"; \
			echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
			echo ""; \
		else \
			echo "⚠️  No active account found in .env"; \
		fi; \
	else \
		echo "⚠️  .env file not found"; \
	fi
	@$(PYTHON_VENV) src/app.py

# Run production server (no debug)
run:
	@echo "🚀 Starting production server..."
	@FLASK_DEBUG=False FLASK_USE_RELOADER=False $(PYTHON_VENV) src/app.py

# Run example/test script (always searches for user info)
test:
	@echo "🧪 Running test script..."
	@if [ -z "$(USERNAME)" ]; then \
		echo "Usage:"; \
		echo "  make test USERNAME=target_account [LIMIT=20]"; \
		echo ""; \
		echo "Examples:"; \
		echo "  make test USERNAME=leomessi"; \
		echo "  make test USERNAME=leomessi LIMIT=10"; \
	else \
		$(PYTHON_VENV) src/test.py $(USERNAME) $(LIMIT); \
	fi

# Stop server (find and kill process on port 5001)
stop:
	@echo "🛑 Stopping server..."
	@lsof -ti:5001 | xargs kill -9 2>/dev/null || echo "No server running on port 5001"
	@echo "✅ Server stopped"

# Clean up cache, session files, and __pycache__
clean:
	@echo "🧹 Cleaning up..."
	@rm -rf __pycache__/
	@rm -rf *.pyc
	@rm -rf *.pyo
	@rm -rf .pytest_cache/
	@rm -rf .mypy_cache/
	@rm -f session.json
	@rm -f followers_*.json
	@find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleanup complete"

# Lint code (if you have flake8 or pylint installed)
lint:
	@echo "🔍 Linting code..."
	@$(PIP) install flake8 >/dev/null 2>&1 || true
	@$(VENV_BIN)/flake8 src/app.py src/test.py --max-line-length=120 --ignore=E501,W503 || echo "Install flake8: pip install flake8"

# Format code (if you have black installed)
format:
	@echo "✨ Formatting code..."
	@$(PIP) install black >/dev/null 2>&1 || true
	@$(VENV_BIN)/black src/app.py src/test.py --line-length=120 || echo "Install black: pip install black"

# Open Python shell with app context
shell:
	@echo "🐍 Opening Python shell..."
	@$(PYTHON_VENV) -i -c "from src.app import app, get_client; print('App and client loaded. Use: app, get_client()')"

# Check if server is running
status:
	@echo "📊 Checking server status..."
	@if lsof -ti:5001 >/dev/null 2>&1; then \
		echo "✅ Server is running on port 5001"; \
		curl -s http://localhost:5001/health | python3 -m json.tool || echo "Server running but health check failed"; \
	else \
		echo "❌ Server is not running"; \
	fi

# Install development dependencies
install-dev:
	@echo "📦 Installing development dependencies..."
	@$(PIP) install flake8 black pytest pytest-cov
	@echo "✅ Development dependencies installed"

# Run tests (if you add pytest tests)
test-pytest:
	@echo "🧪 Running pytest tests..."
	@$(VENV_BIN)/pytest tests/ -v || echo "No tests directory found"

# Create .env file if it doesn't exist
env:
	@if [ ! -f .env ]; then \
		echo "Creating .env file..."; \
		echo "INSTAGRAM_USERNAME=your_username" > .env; \
		echo "INSTAGRAM_PASSWORD=your_password" >> .env; \
		echo "FLASK_PORT=5001" >> .env; \
		echo "FLASK_HOST=0.0.0.0" >> .env; \
		echo "FLASK_DEBUG=True" >> .env; \
		echo "FLASK_USE_RELOADER=False" >> .env; \
		echo "✅ .env file created. Please edit it with your credentials."; \
	else \
		echo ".env file already exists"; \
	fi

