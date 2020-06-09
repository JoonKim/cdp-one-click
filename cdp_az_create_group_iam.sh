#!/bin/bash 


 display_usage() { 
	echo "
Usage:
    $(basename "$0") <base_dir> <prefix> [--help or -h]

Description:
    Creates the appropriate groups for recently create env

Arguments:
    base_dir:       the base directory of the cdp workshop code
    prefix:         prefix for your assets
    --help or -h:   displays this help"

}


generate_post_data()
{
cat<<EOF
[ { "accessorCrn": "${ENVCRN}",
    "role":"${ADMIN_MSI_ID}"
  }
]
EOF
}

# check whether user had supplied -h or --help . If yes display usage 
if [[ ( $1 == "--help") ||  $1 == "-h" ]] 
then 
    display_usage
    exit 0
fi 


# Check the numbers of arguments
if [  $# -lt 2 ] 
then 
    echo "Not enough arguments!" >&2
    display_usage
    exit 1
fi 

if [  $# -gt 2 ] 
then 
    echo "Too many arguments!" >&2
    display_usage
    exit 1
fi 

sleep_duration=3 



# Create groups


if [ $(cdp iam list-groups --group-names "cdp_$2-cdp-env" | wc -l) -gt 0 ]
then
    cdp iam delete-group --group-name "cdp_$2-cdp-env"
fi
sleep $sleep_duration

cdp iam create-group --group-name cdp_$2-cdp-env --no-sync-membership-on-user-login
sleep $sleep_duration

env_crn=$(cdp environments describe-environment --environment-name $2-cdp-env | jq -r .environment.crn)
user_crn=$(cdp iam get-user | jq -r .user.crn)
group_crn=$(cdp iam list-groups --group-names "cdp_$2-cdp-env" | jq -r .groups[0].crn)
cdp iam add-user-to-group --user-id $user_crn --group-name cdp_$2-cdp-env
sleep $sleep_duration

cdp iam assign-group-role \
    --group-name cdp_$2-cdp-env \
    --role "crn:altus:iam:us-west-1:altus:role:PowerUser"
sleep $sleep_duration

cdp iam assign-group-resource-role \
    --group-name cdp_$2-cdp-env \
    --resource-role "crn:altus:iam:us-west-1:altus:resourceRole:EnvironmentAdmin" \
    --resource-crn $env_crn
sleep $sleep_duration

cdp iam assign-group-resource-role \
    --group-name cdp_$2-cdp-env \
    --resource-role "crn:altus:iam:us-west-1:altus:resourceRole:EnvironmentUser" \
    --resource-crn $env_crn
sleep $sleep_duration

# Create IDBroker mappings


ADMIN_MSI_ID=$(az identity list -g "$2-cdp-rg" --query "[?name=='adminIdentity']" | jq -r '.[0].id' | sed -e "s|resourcegroup|resourceGroup|g" )
RANGER_MSI_ID=$(az identity list -g "$2-cdp-rg" --query "[?name=='rangerIdentity']" | jq -r '.[0].id' | sed -e "s|resourcegroup|resourceGroup|g" )
cdp environments set-id-broker-mappings \
               --environment-name "$2-cdp-env" \
               --baseline-role "$RANGER_MSI_ID" \
               --data-access-role "$ADMIN_MSI_ID" \
               --mappings accessorCrn="$group_crn",role="${ADMIN_MSI_ID}"
