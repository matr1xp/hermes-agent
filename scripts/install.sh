#!/bin/bash
# ============================================================================
# Hermes Agent - Cross-Platform Installer
# ============================================================================
# This script installs Hermes Agent on Linux and macOS systems.
# Usage: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
# ============================================================================

set -euo pipefail

# ---- Configuration ----
REPO_OWNER="NousResearch"
REPO_NAME="hermes-agent"
REPO_URL_HTTPS="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
DEFAULT_BRANCH="main"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
VENV_PATH="${HERMES_HOME}/venv"
AGENT_DIR="${HERMES_HOME}/${REPO_NAME}"

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- Helper Functions ----
log()     { echo -e "${GREEN}✓${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
error()   { echo -e "${RED}✗${NC} $1" >&2; }
info()    { echo -e "${BLUE}›${NC} $1"; }
step()    { echo -e "\n${CYAN}▸ $1${NC}"; }

# ---- Prerequisites ----
step "Checking prerequisites..."

# Check for bash 4+
if [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
    error "Hermes requires Bash 4 or higher for associative arrays"
    warn "Try installing a newer Bash: brew install bash (macOS) or apt install bash (Linux)"
    exit 1
fi

# Detect OS
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux*)   OS_TYPE="linux";;
    Darwin*)  OS_TYPE="darwin";;
    *)        error "Unsupported OS: $OS (only Linux and macOS are supported)"; exit 1;;
esac
log "Detected OS: ${OS_TYPE} (${ARCH})"

# Python check
PYTHON=""
for cmd in python3.11 python3.12 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    error "Python 3.10+ is required but not found."
    warn "Install Python 3.10+ from https://python.org before running this installer."
    exit 1
fi
log "Using Python: $($PYTHON --version 2>&1)"

REQUIRED_PYTHON_VERSION=$(python3 -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || echo "0")
if [ "$(printf '%s\n' "3.10" "$REQUIRED_PYTHON_VERSION" | sort -V | head -n1)" != "3.10" ]; then
    error "Python 3.10+ is required (found $REQUIRED_PYTHON_VERSION)"
    exit 1
fi

# Git check
if ! command -v git &>/dev/null; then
    error "Git is required but not found."
    warn "Install Git from https://git-scm.com before running this installer."
    exit 1
fi
log "Git: $(git --version 2>&1)"

# uv check (preferred) or pip fallback
HAS_UV=false
if command -v uv &>/dev/null; then
    HAS_UV=true
    log "uv: $(uv --version 2>&1)"
else
    warn "uv not found — will use pip instead (slower). Install uv from https://docs.astral.sh/uv/ for faster installs."
fi

# ---- Install ----
step "Installing Hermes Agent to ${AGENT_DIR}"

# Clone or update
if [ -d "$AGENT_DIR/.git" ]; then
    info "Repository exists — updating..."
    cd "$AGENT_DIR"
    git remote set-url origin "$REPO_URL_HTTPS" 2>/dev/null || true
    if ! git stash -u && git pull --rebase origin "$DEFAULT_BRANCH"; then
        warn "Update failed, trying fresh clone..."
        rm -rf "$AGENT_DIR"
        git clone --depth 1 --branch "$DEFAULT_BRANCH" "$REPO_URL_HTTPS" "$AGENT_DIR"
    fi
else
    info "Cloning repository..."
    git clone --depth 1 --branch "$DEFAULT_BRANCH" "$REPO_URL_HTTPS" "$AGENT_DIR"
fi
cd "$AGENT_DIR"

# Create venv
step "Setting up Python virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    $PYTHON -m venv "$VENV_PATH"
    log "Virtual environment created at ${VENV_PATH}"
fi

# Activate
source "${VENV_PATH}/bin/activate"

# Install dependencies
step "Installing Python dependencies..."
if [ "$HAS_UV" = true ]; then
    uv pip install --quiet --upgrade -e ".[dev]" 2>/dev/null || \
    uv pip install --quiet --upgrade -e "." 2>/dev/null || {
        warn "uv install failed, falling back to pip..."
        pip install --quiet --upgrade -e .
    }
else
    pip install --quiet --upgrade -e .
fi
log "Dependencies installed"

# Create hermes wrapper
step "Creating 'hermes' command..."
WRAPPER_DIR="${HERMES_HOME}/bin"
mkdir -p "$WRAPPER_DIR"

cat > "${WRAPPER_DIR}/hermes" << 'WRAPPER'
#!/bin/bash
VENV_PATH="${HERMES_HOME:-$HOME/.hermes}/venv"
AGENT_DIR="${HERMES_HOME:-$HOME/.hermes}/hermes-agent"
source "${VENV_PATH}/bin/activate"
exec python "${AGENT_DIR}/cli.py" "$@"
WRAPPER

chmod +x "${WRAPPER_DIR}/hermes"

# Add to PATH
if ! echo "$PATH" | grep -q "$WRAPPER_DIR"; then
    SHELL_CONFIG=""
    case "$SHELL" in
        */zsh) SHELL_CONFIG="$HOME/.zshrc" ;;
        */bash) SHELL_CONFIG="$HOME/.bashrc" ;;
    esac
    if [ -n "$SHELL_CONFIG" ]; then
        echo "" >> "$SHELL_CONFIG"
        echo "# Hermes Agent" >> "$SHELL_CONFIG"
        echo "export PATH=\"\$PATH:${WRAPPER_DIR}\"" >> "$SHELL_CONFIG"
        info "Added ${WRAPPER_DIR} to PATH in ${SHELL_CONFIG}"
    fi
    # Also set for current session
    export PATH="${PATH}:${WRAPPER_DIR}"
fi

# Create .env template if not exists
if [ ! -f "${HERMES_HOME}/.env" ]; then
    cat > "${HERMES_HOME}/.env" << 'ENV'
# Hermes Agent Configuration
# Get your API key from https://openrouter.ai/keys
OPENROUTER_API_KEY=
ENV
    warn "Created ${HERMES_HOME}/.env — add your API keys to get started"
fi

# ---- Verify ----
step "Verifying installation..."
if "${WRAPPER_DIR}/hermes" doctor 2>/dev/null; then
    log "Installation verified ✓"
else
    warn "Post-install check had minor issues — try 'hermes doctor --fix' after setup"
fi

# ---- Done ----
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Hermes Agent installed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${CYAN}Quick start:${NC}"
echo -e "  Run ${YELLOW}hermes${NC} to start interactive chat"
echo -e "  Run ${YELLOW}hermes setup${NC} to configure model, tools, and gateway"
echo -e "  Run ${YELLOW}hermes model${NC} to pick a model/provider"
echo ""
echo -e "  ${CYAN}Next steps:${NC}"
echo -e "  1. Add API keys to ${YELLOW}${HERMES_HOME}/.env${NC}"
echo -e "  2. Run ${YELLOW}hermes setup${NC} for guided configuration"
echo -e "  3. Start chatting with ${YELLOW}hermes${NC}"
echo ""
echo -e "  ${CYAN}Need help?${NC} https://hermes-agent.nousresearch.com/docs"
echo ""
