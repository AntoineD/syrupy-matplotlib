set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

python := env('UV_PYTHON', '3.10')

@_:
    just --list

# Run tests
[group('qa')]
test *args:
    uv run --python {{python}} pytest {{args}}

# Test with minimum dependency versions
[group('qa')]
test-min-deps *args:
    uv run --python 3.10 --with 'numpy==1.26' --resolution lowest-direct pytest {{args}}

# Run tests coverage
[group('qa')]
coverage *args:
    just test --cov --cov-report=xml --cov-report=html --no-cov-on-fail {{args}}

# Run code formatting and checking
[group('qa')]
check *args:
    uv run prek install
    uv run prek run --all-files {{args}}

# Run code formatting and checking
[group('qa')]
check-typing *args:
    uv run ty check {{args}}

# Create and check PyPI distribution
[group('packaging')]
dist:
    uv build --clear

# Upload distribution to package repository
[group('packaging')]
publish: dist
    uv publish

# Update dependencies
[group('lifecycle')]
update:
    uv lock --upgrade
    uv run prek autoupdate

# Ensure project virtualenv is up to date and has the base dependencies
[group('lifecycle')]
install *args:
    uv sync --python {{python}} {{args}}

# Remove temporary files
[group('lifecycle')]
clean:
    rm -rf .venv .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
    find . -type d -name "__pycache__" -exec rm -r {} +

# Recreate project virtualenv from scratch
[group('lifecycle')]
fresh: clean install
