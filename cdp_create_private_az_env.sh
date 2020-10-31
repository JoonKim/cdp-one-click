#!/bin/bash 
set -o nounset

display_usage() { 
    echo "
Usage:
    $(basename "$0") [--help or -h] <prefix> <credential> <region> <key> <sg_cidr> (<network_created>)

Description:
    Launches a CDP Azure environment

Arguments:
    prefix:             prefix for your assets
    credentials:        CDP credential name
    region:             region for your env
    key:                name of the Azure key to re-use
    sg_cidr:            CIDR to open in your security group
    network_created:    (optional) flag to see if network was created (possible values: yes or no)
    --help or -h:   displays this help"

}

# check whether user had supplied -h or --help . If yes display usage 
if [[ ( ${1:-x} == "--help") ||  ${1:-x} == "-h" ]] 
then 
    display_usage
    exit 0
fi 


# Check the numbers of arguments
if [  $# -lt 6 ] 
then 
    echo "Not enough arguments!" >&2
    display_usage
    exit 1
fi 

if [  $# -gt 7 ] 
then 
    echo "Too many arguments!" >&2
    display_usage
    exit 1
fi 

flatten_tags() {
    tags=$1
    flattened_tags=""
    for item in $(echo ${tags} | jq -r '.[] | @base64'); do
        _jq() {
            echo ${item} | base64 --decode | jq -r ${1}
        }
        #echo ${item} | base64 --decode
        key=$(_jq '.key')
        value=$(_jq '.value')
        flattened_tags=$flattened_tags" key=\"$key\",value=\"$value\""
    done
    echo $flattened_tags
}


prefix=$1
credential=$2
region=$3
key=$4
sg_cidr=$5
workload_analytics=$6


network_created="no"
if [  $# -eq 7 ] 
then 
    network_created=$7
    network_id="$prefix-cdp-vnet"
    subnet_1="$prefix-priv-subnet-1"
    subnet_2="$prefix-priv-subnet-2"
    subnet_3="$prefix-priv-subnet-3"
    knox_nsg=$(az network nsg show -g $prefix-cdp-rg -n $prefix-knox-nsg | jq -r .id)
    default_nsg=$(az network nsg show -g $prefix-cdp-rg -n $prefix-default-nsg | jq -r .id)
    
fi
owner=$(cdp iam get-user | jq -r .user.email)
SUBSCRIPTION_ID=$(az account show | jq -r .id)
if [[ "$network_created" == "no" ]]
then
    cdp environments create-azure-environment  --environment-name ${prefix}-cdp-env \
        --credential-name ${credential} \
        --region "${region}" \
        --public-key "${key}" \
        --security-access cidr="$sg_cidr" \
        --log-storage storageLocationBase="abfs://logs@${prefix//-/}cdpsa.dfs.core.windows.net",managedIdentity="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${prefix}-cdp-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/loggerIdentity" \
        --new-network-params networkCidr="10.10.0.0/16" \
        --tags $(flatten_tags $TAGS)  \
        --no-use-public-ip \
        --enable-tunnel \
        $workload_analytics
else
    cdp environments create-azure-environment  --environment-name ${prefix}-cdp-env \
        --credential-name ${credential} \
        --region "${region}" \
        --public-key "${key}" \
        --security-access securityGroupIdForKnox="$knox_nsg",defaultSecurityGroupId="$default_nsg" \
        --log-storage storageLocationBase="abfs://logs@${prefix//-/}cdpsa.dfs.core.windows.net",managedIdentity="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${prefix}-cdp-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/loggerIdentity" \
        --existing-network-params networkId="$network_id",resourceGroupName="$prefix-cdp-rg",subnetIds="$subnet_1","$subnet_2","$subnet_3" \
        --tags $(flatten_tags $TAGS)  \
        --no-use-public-ip \
        --enable-tunnel \
        $workload_analytics
fi


