#!/bin/bash
#
# Ingest GeoJSON files into Cloudera Operational Database (COD / managed HBase)
# on AWS CDP Public Cloud, using GeoMesa's HBase DataStore.
#
# This is the "storage in COD" companion to the geospatial parameters sample
# (parameters_sample/parameters_aws_geospatial.json). It:
#   1. ensures the COD database from your parameter file exists (creates + waits
#      if needed),
#   2. downloads the COD HBase client configuration (hbase-site.xml, truststore)
#      via `cdp opdb describe-client-connectivity`,
#   3. optionally uploads local GeoJSON to the data lake S3 bucket, and
#   4. runs `geomesa-hbase ingest` to write each GeoJSON feature into HBase.
#
# HBase is not a file store: GeoMesa maps every GeoJSON *feature* to HBase rows
# with space-filling-curve spatial indexes so you can run bbox/CQL queries. The
# original files, if you want to keep them, belong in object storage (use
# --upload-to-s3 for that).
#
# Prerequisites (this repo installs cdp + aws; GeoMesa you provide yourself):
#   * cdp CLI authenticated (~/.cdp/credentials) and AWS CLI authenticated
#   * geomesa-hbase tools on PATH (https://www.geomesa.org/documentation/)
#   * network reachability to the COD HBase endpoints (run from a host with
#     access to the environment's network, e.g. a cluster edge node or VPN)
#
# Usage:
#   ingest_geojson_geomesa.sh <parameter_file> <geojson_source> [options]
#
#   <geojson_source>  Local directory/file/glob (e.g. /path/data/entity) or an
#                     s3://... path already in object storage.
#
# Options:
#   --database <name>     COD database to use (default: first op_db_list entry)
#   --catalog <name>      HBase catalog table (default: <prefix>_geomesa)
#   --feature <name>      SimpleFeatureType name (default: entity)
#   --sft <spec|name>     GeoMesa SFT; omit to let GeoMesa infer from the data
#   --converter <name>    GeoMesa converter; omit to infer (default when --sft
#                         is also omitted)
#   --upload-to-s3 <uri>  Copy a local <geojson_source> to this s3:// location
#                         first, then ingest from there
#   -h, --help            Show this help

# prefix, cloud_provider, op_db_list, workload_* and friends are populated by
# parse_parameters in common.sh (sourced below), matching every other script here.
# shellcheck disable=SC2154
# shellcheck source=/dev/null

if [ -n "${DEV_CLI+x}" ]; then
    shopt -s expand_aliases
    alias cdp="cdp 2>/dev/null"
fi
source "$(cd "$(dirname "$0")" && pwd -L)/../common.sh"

display_usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
}

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    display_usage
    exit 0
fi

if [ "$#" -lt 2 ]; then
    echo "Not enough arguments!" >&2
    display_usage
    exit 1
fi

param_file="$1"; shift
geojson_source="$1"; shift

db_override=""
catalog=""
feature="entity"
sft=""
converter=""
s3_target=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --database)     db_override="$2"; shift 2 ;;
        --catalog)      catalog="$2"; shift 2 ;;
        --feature)      feature="$2"; shift 2 ;;
        --sft)          sft="$2"; shift 2 ;;
        --converter)    converter="$2"; shift 2 ;;
        --upload-to-s3) s3_target="$2"; shift 2 ;;
        -h|--help)      display_usage; exit 0 ;;
        *)              echo "Error: unsupported argument '$1'" >&2; display_usage; exit 1 ;;
    esac
done

# Parse the parameter file (sets prefix, workload_user, workload_pwd,
# cloud_provider, etc.) and run the standard cdp/aws pre-checks.
parse_parameters "$param_file"
run_pre_checks

if [[ "$cloud_provider" != "aws" ]]; then
    handle_exception 1 "$prefix" "geomesa ingest" "This helper targets AWS CDP; cloud_provider is '$cloud_provider'"
fi

if ! command -v geomesa-hbase >/dev/null 2>&1; then
    handle_exception 1 "$prefix" "geomesa verification" \
        "geomesa-hbase is not on PATH. Install the GeoMesa HBase command-line tools first (https://www.geomesa.org/documentation/)."
fi

# Resolve the COD database name: explicit override, else first op_db_list entry.
database_name="$db_override"
if [ -z "$database_name" ]; then
    database_name=$(echo "$op_db_list" | jq -r '.[0].database_name // empty')
fi
if [ -z "$database_name" ]; then
    handle_exception 1 "$prefix" "geomesa ingest" \
        "No COD database specified. Add one to op_db_list in $param_file or pass --database <name>."
fi

env_name="${prefix}-cdp-env"
[ -z "$catalog" ] && catalog="${prefix}_geomesa"

echo "⏱  $(date +%H%Mhrs)"
echo ""
echo "Ingesting GeoJSON into COD/HBase for ${prefix}:"
echo "▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔"
echo "  environment : ${env_name}"
echo "  database    : ${database_name}"
echo "  catalog     : ${catalog}"
echo "  feature     : ${feature}"
echo ""

# 1. Ensure the COD database is AVAILABLE (create + wait if necessary).
db_status=$(cdp opdb describe-database --environment-name "$env_name" --database-name "$database_name" 2>/dev/null | jq -r .databaseDetails.status)
[ -z "$db_status" ] && db_status="NOT_FOUND"

if [[ "$db_status" == "NOT_FOUND" ]]; then
    result=$(cdp opdb create-database --environment-name "$env_name" --database-name "$database_name" 2>&1 >/dev/null)
    handle_exception $? "$prefix" "COD database creation" "$result"
fi

if [[ "$db_status" != "AVAILABLE" ]]; then
    spin='🌑🌒🌓🌔🌕🌖🌗🌘'
    i=0
    while [ "$db_status" != "AVAILABLE" ]; do
        i=$(((i + 1) % 8))
        printf "\r%s  %s: %s status: %s                    " "${spin:$i:1}" "$prefix" "$database_name" "$db_status"
        sleep 5
        db_status=$(cdp opdb describe-database --environment-name "$env_name" --database-name "$database_name" 2>/dev/null | jq -r .databaseDetails.status)
        [ -z "$db_status" ] && db_status="NOT_FOUND"
    done
    echo ""
fi
echo "${CHECK_MARK}  ${prefix}: COD database ${database_name} is AVAILABLE"

# 2. Fetch COD client connectivity and materialize the HBase client config so
#    GeoMesa can find hbase-site.xml on its classpath.
conf_dir="/tmp/${prefix}-cod-hbase-conf"
rm -rf "$conf_dir"; mkdir -p "$conf_dir"
conn_json="${conf_dir}/client-connectivity.json"

cdp opdb describe-client-connectivity --environment-name "$env_name" --database-name "$database_name" > "$conn_json" 2>/dev/null
handle_exception $? "$prefix" "COD client connectivity" "Could not describe client connectivity"

# The HBase connector exposes a downloadable client-configuration archive. Field
# names vary slightly across CLI versions, so try the common ones defensively.
hbase_cfg_url=$(jq -r '
  .connectors[]?
  | select((.name // "" | ascii_downcase | test("hbase")) or (.kind // "" | ascii_downcase | test("hbase")))
  | (.configuration.clientConfigurationURL // .configuration.url // .clientConfigurationURL // empty)
' "$conn_json" | head -1)

if [ -n "$hbase_cfg_url" ]; then
    curl -fsSL "$hbase_cfg_url" -o "${conf_dir}/hbase-client-config.zip" \
        && unzip -oq "${conf_dir}/hbase-client-config.zip" -d "$conf_dir" \
        && echo "${CHECK_MARK}  ${prefix}: downloaded HBase client configuration"
else
    echo "${ALREADY_DONE}  ${prefix}: no client-configuration URL found in connectivity output."
    echo "    Review ${conn_json} and place the COD hbase-site.xml under ${conf_dir} manually,"
    echo "    or download it from the COD UI (Databases > ${database_name} > HBase Client Configuration)."
fi

# GeoMesa picks up Hadoop/HBase config from the classpath.
hbase_site=$(find "$conf_dir" -name 'hbase-site.xml' 2>/dev/null | head -1)
if [ -n "$hbase_site" ]; then
    hbase_conf_dir=$(dirname "$hbase_site")
    export HADOOP_CONF_DIR="$hbase_conf_dir"
    export GEOMESA_EXTRA_CLASSPATHS="${GEOMESA_EXTRA_CLASSPATHS:+$GEOMESA_EXTRA_CLASSPATHS:}$hbase_conf_dir"
fi

# 3. Optionally stage local files into object storage before ingest.
ingest_path="$geojson_source"
if [ -n "$s3_target" ]; then
    if [[ "$geojson_source" == s3://* ]]; then
        handle_exception 1 "$prefix" "s3 upload" "Source is already an s3:// path; drop --upload-to-s3"
    fi
    aws s3 cp "$geojson_source" "$s3_target" --recursive
    handle_exception $? "$prefix" "s3 upload" "Failed uploading GeoJSON to $s3_target"
    ingest_path="$s3_target"
    echo "${CHECK_MARK}  ${prefix}: uploaded GeoJSON to ${s3_target}"
fi

# 4. Run the GeoMesa HBase ingest. When --sft/--converter are omitted, GeoMesa
#    infers the schema from the GeoJSON (accepted non-interactively via --force).
ingest_args=(ingest -c "$catalog" -f "$feature" --force)
if [ -n "$sft" ]; then ingest_args+=(-s "$sft"); fi
if [ -n "$converter" ]; then ingest_args+=(-C "$converter"); fi
if [ -z "$sft" ] && [ -z "$converter" ]; then ingest_args+=(--input-format geojson); fi
ingest_args+=("$ingest_path")

echo ""
echo "Running: geomesa-hbase ${ingest_args[*]}"
geomesa-hbase "${ingest_args[@]}"
handle_exception $? "$prefix" "geomesa ingest" "GeoMesa ingest failed"

echo ""
echo "${CHECK_MARK}  ${prefix}: GeoJSON ingested into COD/HBase (catalog ${catalog}, feature ${feature})"
echo "   Verify with: geomesa-hbase describe-schema -c ${catalog} -f ${feature}"
echo "                geomesa-hbase export -c ${catalog} -f ${feature} -m 5"
