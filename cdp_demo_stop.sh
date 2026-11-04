#!/usr/bin/env bash
#
# Stop ALL CDP services for the demo to save cost (reverse of cdp_demo_start.sh).
#
# For a CDP deployment the correct way to power down the underlying AWS EC2
# instances is THROUGH CDP -- stop the Data Hubs and COD, then stop the
# Environment (which stops the Data Lake + FreeIPA). Do NOT `aws ec2
# stop-instances` directly: CDP's auto-repair would fight it and the clusters
# may not come back cleanly.
#
# Usage:
#   ./cdp_demo_stop.sh <parameter_file>
#   e.g. ./cdp_demo_stop.sh parameters/parameters_aws_sandbox.json
#
# Only the CDP CLI + jq are required (no AWS CLI needed).
set -uo pipefail

PARAM_FILE="${1:-}"
if [ -z "$PARAM_FILE" ] || [ "$PARAM_FILE" = "-h" ] || [ "$PARAM_FILE" = "--help" ]; then
  echo "Usage: $(basename "$0") <parameter_file>" >&2
  exit 1
fi
command -v cdp >/dev/null 2>&1 || { echo "cdp CLI not found" >&2; exit 1; }
command -v jq  >/dev/null 2>&1 || { echo "jq not found" >&2; exit 1; }

prefix=$(jq -r '.required.prefix' "$PARAM_FILE")
CDP_PROFILE=$(jq -r '.optional.cdp_profile // "default"' "$PARAM_FILE")
export CDP_PROFILE
env_name="${prefix}-cdp-env"

# Data Hubs attached to the environment, excluding COD (managed via `opdb`).
datahubs() {
  cdp datahub list-clusters --environment-name "$env_name" 2>/dev/null \
    | jq -r '.clusters[]? | select((.clusterName|startswith("cod-")|not) and (((.workloadType//"")|test("COD"))|not)) | .clusterName'
}
cod_dbs() { jq -r '.required.op_db_list[]?.database_name // empty' "$PARAM_FILE"; }

get_status() {
  case "$1" in
    dh)  cdp datahub describe-cluster --cluster-name "$2" 2>/dev/null | jq -r '.cluster.status // "UNKNOWN"' ;;
    cod) cdp opdb describe-database --environment-name "$env_name" --database-name "$2" 2>/dev/null | jq -r '.databaseDetails.status // "UNKNOWN"' ;;
    env) cdp environments describe-environment --environment-name "$env_name" 2>/dev/null | jq -r '.environment.status // "UNKNOWN"' ;;
  esac
}
wait_for() { # type name target label timeout
  local type=$1 name=$2 target=$3 label=$4 timeout=${5:-1800} i=0 st
  while :; do
    st=$(get_status "$type" "$name")
    [ "$st" = "$target" ] && { printf "\r  %s -> %s                 \n" "$label" "$target"; return 0; }
    case "$st" in *FAILED*|UNKNOWN) printf "\r  %s -> %s (continuing)      \n" "$label" "$st"; return 0 ;; esac
    i=$((i + 10)); if [ "$i" -ge "$timeout" ]; then printf "\r  %s -> timeout (last=%s)\n" "$label" "$st"; return 0; fi
    printf "\r  %s -> %s ...        " "$label" "$st"; sleep 10
  done
}

echo "Stopping CDP services for environment: $env_name  (profile: $CDP_PROFILE)"

# 1. Stop Data Hubs
for dh in $(datahubs); do
  echo "- Stopping Data Hub: $dh"
  cdp datahub stop-cluster --cluster-name "$dh" 2>/dev/null || true
done
# 2. Stop COD databases
for db in $(cod_dbs); do
  echo "- Stopping COD database: $db"
  cdp opdb stop-database --environment-name "$env_name" --database-name "$db" 2>/dev/null || true
done
# 3. Wait for compute to stop before stopping the environment
for dh in $(datahubs); do wait_for dh  "$dh" STOPPED "Data Hub $dh" 1800; done
for db in $(cod_dbs);  do wait_for cod "$db" STOPPED "COD $db"      1800; done
# 4. Stop the environment (Data Lake + FreeIPA)
echo "- Stopping environment (Data Lake + FreeIPA): $env_name"
cdp environments stop-environment --environment-name "$env_name" 2>/dev/null || true
wait_for env "$env_name" ENV_STOPPED "Environment" 2400

echo ""
echo "All CDP services stopped; the underlying AWS instances are powered down."
echo "Restart for the next demo with:  ./cdp_demo_start.sh $PARAM_FILE"
