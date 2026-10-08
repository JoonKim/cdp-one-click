#!/usr/bin/env bash
#
# Per-boot runtime setup for the cdp-one-click Cloud Agent environment.
#
# Cloud Agent Secrets are injected as environment variables on every boot, but
# the cdp CLI (and the wrapper scripts in this repo) read credentials from the
# ~/.cdp/ directory. This script materializes ~/.cdp/credentials from Secrets so
# the `cdp` CLI can authenticate. It is intentionally:
#   * idempotent            - safe to run on every boot; it rewrites the file
#   * non-fatal when unset  - no-ops (exit 0) if the Secrets are not configured,
#                             so the environment still starts for read-only work
#   * secret-safe           - never echoes secret values; writes a 0600 file
#
# Configure these as environment Secrets to enable authenticated `cdp` calls:
#   CDP_ACCESS_KEY_ID   - the "Access Key ID" from your CDP CLI credential
#   CDP_PRIVATE_KEY     - the matching "Private Key" (single-line string)
#   CDP_PROFILE_NAME    - optional; the profile name to write (default: "default")
#
# Cloud provider credentials (needed to actually provision infrastructure) are
# read natively by their CLIs, so expose them as Secrets too when needed:
#   AWS:   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (+ optional AWS_SESSION_TOKEN)
#   Azure: use `az login` (e.g. a service principal) in your own start hook
#   GCP:   GOOGLE_APPLICATION_CREDENTIALS pointing at a mounted key file
set -euo pipefail

if [ -z "${CDP_ACCESS_KEY_ID:-}" ] || [ -z "${CDP_PRIVATE_KEY:-}" ]; then
  echo "start: CDP_ACCESS_KEY_ID / CDP_PRIVATE_KEY not set; skipping ~/.cdp setup." \
       "(Add them as environment Secrets to enable authenticated cdp calls.)"
  exit 0
fi

profile="${CDP_PROFILE_NAME:-default}"
cdp_dir="${HOME}/.cdp"
cred_file="${cdp_dir}/credentials"

umask 077
mkdir -p "${cdp_dir}"

# Write the credential file with restrictive permissions. A single profile is
# written deterministically so repeated boots converge to the same state.
{
  printf '[%s]\n' "${profile}"
  printf 'cdp_access_key_id = %s\n' "${CDP_ACCESS_KEY_ID}"
  printf 'cdp_private_key = %s\n' "${CDP_PRIVATE_KEY}"
} > "${cred_file}"
chmod 600 "${cred_file}"

echo "start: wrote CDP credentials for profile '${profile}' to ${cred_file}."
