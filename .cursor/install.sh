#!/usr/bin/env bash
#
# Idempotent environment bootstrap for the cdp-one-click repository.
#
# This repo is a collection of Bash wrapper scripts that orchestrate the
# Cloudera CDP CLI together with the AWS, Azure and GCP cloud CLIs and jq.
# There is no application to compile; "installing dependencies" means making
# those command-line tools available and on PATH.
#
# The script is safe to run repeatedly: every step checks for an existing
# installation before doing any work.
set -euo pipefail

log() { printf '\n=== %s ===\n' "$*"; }

APT_UPDATED=0
apt_install() {
  if [ "${APT_UPDATED}" -eq 0 ]; then
    sudo apt-get update -y
    APT_UPDATED=1
  fi
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

# ---------------------------------------------------------------------------
# Base utilities used by the scripts and by the installers below.
# ---------------------------------------------------------------------------
log "Base utilities (jq, curl, unzip, git, shellcheck, python)"
NEED_PKGS=()
for pkg_cmd in "jq:jq" "curl:curl" "unzip:unzip" "git:git" "shellcheck:shellcheck" "gpg:gnupg"; do
  cmd="${pkg_cmd%%:*}"; pkg="${pkg_cmd##*:}"
  command -v "$cmd" >/dev/null 2>&1 || NEED_PKGS+=("$pkg")
done
command -v pip3 >/dev/null 2>&1 || NEED_PKGS+=(python3-pip)
python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || NEED_PKGS+=(python3-venv)
if [ "${#NEED_PKGS[@]}" -gt 0 ]; then
  apt_install "${NEED_PKGS[@]}"
else
  echo "All base utilities already present."
fi

# ---------------------------------------------------------------------------
# Cloudera CDP CLI (the primary tool driven by every wrapper script).
# Installed system-wide so `cdp` is always on PATH for non-interactive shells.
# ---------------------------------------------------------------------------
log "Cloudera CDP CLI (cdpcli)"
if command -v cdp >/dev/null 2>&1; then
  echo "cdp already installed: $(cdp --version 2>&1)"
else
  sudo pip3 install --break-system-packages --no-input cdpcli
fi

# ---------------------------------------------------------------------------
# AWS CLI v2 (official bundle -> /usr/local/bin/aws).
# ---------------------------------------------------------------------------
log "AWS CLI v2"
if command -v aws >/dev/null 2>&1; then
  echo "aws already installed: $(aws --version 2>&1)"
else
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "${tmp}/awscliv2.zip"
  unzip -q "${tmp}/awscliv2.zip" -d "${tmp}"
  sudo "${tmp}/aws/install" --update
  rm -rf "${tmp}"
fi

# ---------------------------------------------------------------------------
# Azure CLI (official Microsoft apt repository -> /usr/bin/az).
# ---------------------------------------------------------------------------
log "Azure CLI"
if command -v az >/dev/null 2>&1; then
  echo "az already installed: $(az version --output tsv 2>/dev/null | head -1)"
else
  curl -fsSL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi

# ---------------------------------------------------------------------------
# Google Cloud SDK (official Google apt repository -> /usr/bin/gcloud).
# ---------------------------------------------------------------------------
log "Google Cloud SDK (gcloud)"
if command -v gcloud >/dev/null 2>&1; then
  echo "gcloud already installed: $(gcloud --version 2>&1 | head -1)"
else
  sudo install -m 0755 -d /usr/share/keyrings
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/cloud.google.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends google-cloud-cli
fi

log "Tool versions"
printf 'jq:         %s\n' "$(jq --version 2>&1)"
printf 'cdp:        %s\n' "$(cdp --version 2>&1)"
printf 'aws:        %s\n' "$(aws --version 2>&1)"
printf 'az:         %s\n' "$(az version --output tsv 2>/dev/null | head -1)"
printf 'gcloud:     %s\n' "$(gcloud --version 2>&1 | head -1)"
printf 'shellcheck: %s\n' "$(shellcheck --version 2>&1 | awk '/version:/{print $2}' | head -1)"

log "cdp-one-click environment ready"
