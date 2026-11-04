#!/usr/bin/env bash
#
# Start ALL CDP services for the demo (reverse of cdp_demo_stop.sh).
#
# Order matters: the Environment (FreeIPA + Data Lake) must be up before the
# Data Hubs and COD can start. This brings the underlying AWS EC2 instances back
# online cleanly through CDP.
#
# Usage:
#   ./cdp_demo_start.sh <parameter_file>
#   e.g. ./cdp_demo_start.sh parameters/parameters_aws_sandbox.json
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
dl_name="${prefix}-cdp-dl"

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
    dl)  cdp datalake describe-datalake --datalake-name "$2" 2>/dev/null | jq -r '.datalake.status // "UNKNOWN"' ;;
  esac
}
wait_for() { # type name target label timeout
  local type=$1 name=$2 target=$3 label=$4 timeout=${5:-2400} i=0 st
  while :; do
    st=$(get_status "$type" "$name")
    [ "$st" = "$target" ] && { printf "\r  %s -> %s                 \n" "$label" "$target"; return 0; }
    case "$st" in *FAILED*|UNKNOWN) printf "\r  %s -> %s (continuing)      \n" "$label" "$st"; return 1 ;; esac
    i=$((i + 10)); if [ "$i" -ge "$timeout" ]; then printf "\r  %s -> timeout (last=%s)\n" "$label" "$st"; return 1; fi
    printf "\r  %s -> %s ...        " "$label" "$st"; sleep 10
  done
}

echo "Starting CDP services for environment: $env_name  (profile: $CDP_PROFILE)"

# 1. Environment (FreeIPA + Data Lake) first
echo "- Starting environment: $env_name"
cdp environments start-environment --environment-name "$env_name" 2>/dev/null || true
wait_for env "$env_name" AVAILABLE "Environment" 2400
wait_for dl  "$dl_name"  RUNNING   "Data Lake"   2400

# 2. COD databases
for db in $(cod_dbs); do
  echo "- Starting COD database: $db"
  cdp opdb start-database --environment-name "$env_name" --database-name "$db" 2>/dev/null || true
done
# 3. Data Hubs
for dh in $(datahubs); do
  echo "- Starting Data Hub: $dh"
  cdp datahub start-cluster --cluster-name "$dh" 2>/dev/null || true
done

# 4. Wait for everything to be ready
for db in $(cod_dbs);  do wait_for cod "$db" AVAILABLE "COD $db"      2400; done
for dh in $(datahubs); do wait_for dh  "$dh" AVAILABLE "Data Hub $dh" 2400; done

echo ""
echo "All CDP services are up. Demo is ready."
echo "Stop everything afterwards with:  ./cdp_demo_stop.sh $PARAM_FILE"
