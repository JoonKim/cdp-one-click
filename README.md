# CDP setup in one click

This repository contains a set of scripts that will create CDP minimal assets for demo in one wrapper script, including:
* Cloud pre-requisites (bucket, policies, roles, network)
* Cloud CDP Environmment
* CDP Data Lake
* Any CDP Data Hub cluster definition


# Pre-Requisites

## AWS
* AWS CLI ([Instructions](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-install.html))
    * You must run `aws configure` after install, and ensure your region is set
* AWS ssh key ([Instructions](https://docs.aws.amazon.com/opsworks/latest/userguide/security-settingsshkey.html)); Alternatively, you can use the `field` or `_field` keys setup in our AWS SE accounts

## Azure
* Azure CLI ([Instructions](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest))
    * Use `az login` after install to login
* ssh Key: you will need to paste the public key into your parameters file

_Note: Azure CML is not supported yet, so don't add it in your parameters file :)_

## CDP
* CDP CLI ([Instructions](https://docs.cloudera.com/management-console/cloud/cli/topics/mc-cli-client-setup.html))

* CDP Credential ([Instructions](https://docs.cloudera.com/management-console/cloud/credentials-aws/topics/mc-create-credentialrole.html))
    * You must set your `Workload Password` in your `CDP Profile` ([Shortcut](https://console.cdp.cloudera.com/iam/index.html#/my-account))
    * You must generate a `CLI Access Key` in your `CDP Profile`, and configure it to your local `CDP CLI` ([Shortcut](https://console.cdp.cloudera.com/iam/index.html#/my-account))
    * Your user should have minimally EnvironmentCreator and IamUser as roles


# Parameters file format

## Detailed format

<pre>
{
    <b><em>Required parameters: </em></b>
    "required": {
                
        <b><em>Prefix used for cdp assets creation: </em></b> 
        "prefix":         "pvi",
        
        <b><em>Name of credential to use: </em></b>
        "credential":     "pvidal-aws-se-credential",

        <b><em>Region to use (should also be the default region of your cloud provider cli profile): </em></b>
        "region":         "us-east-1",
        
        <b><em>ssh key to use for cdp instances setup: </em></b>
        "key":            "field",

        <b><em>Workload password to use in CDP: </em></b>
        "workload_pwd":   "cdpw0rksh0p",

        <b><em>Array of datahub to setup (can be empty): </em></b>
        "datahub_list": [

            <b><em>Element 1: </em></b>
            {
                <b><em>Definition from cdp-cluster-definitions folder: </em></b>
                "definition": "data-mart.json",

                <b><em>Custom script from cdp-dh-custom-scripts folder: </em></b>
                "custom_script": ""
            },

            <b><em>Element 2: </em></b>
            {
                <b><em>Definition from cdp-cluster-definitions folder: </em></b>
                "definition": "cdp-mod-workshop.json",

                <b><em>Custom script from cdp-dh-custom-scripts folder: </em></b>
                "custom_script": "cdp_mod_wkp.sh"
            },
        ],

        <b><em>Array of ml workspaces to setup (can be empty): </em></b>
        "ml_workspace_list": [

            <b><em>Element 1: </em></b>
            {
                <b><em>Definition from cml-workspace-definitions folder: </em></b>
                "definition": "small_workspace.json",

                <b><em>Flag to enable monitoring, governance and model metrics (possible values yes or no): </em></b>
                "enable_workspace": "no"
            }

        ],

        <b><em>Array of op database to setup (can be empty): </em></b>
        "op_db_list": [

            <b><em>Element 1: </em></b>
            {
                <b><em>Name of the database you want to create: </em></b>
                "database_name": "your_db_name"
            }

        ],
        <b><em>Array of CDW vw to setup (can be empty): </em></b>
        "dw_list": [

            <b><em>Element 1: </em></b>
            {
                <b><em>Name of the vw you want to create: </em></b>
                "name": "vw-name",
                <b><em>Type of vw you want to create: </em></b>
                "type": "hive"
            }
        ]
    },

    <b><em>Optional (defaulted) parameters (can be empty): </em></b>
    "optional": {

        <b><em>Cloud provider (default: aws, possible values: aws, az): </em></b>
        "cloud_provider": "aws", 

        <b><em>Cloud provider cli profile (AWS-your profile name / AZ-your subscription name or ID) (default: default): </em></b>
        "cloud_profile":    "default",

        <b><em>CDP cli profile (default: default): </em></b>
        "cdp_profile":    "default",

        <b><em>Flag to create cdp credential or not (default: no, possible values: yes, no) </em></b>
        "generate_credential": "no",

        <b><em>NOT SUPPORTED YET Flag to generate minimal cross account role policy or not (default: no, possible values: yes, no) </em></b>
        "generate_minimal_cross_account": "no",

        <b><em>Flag to create network in cloud provider or not (default: no, possible values: yes, no) </em></b>
        "create_network": "no",

        <b><em>CIDR to open in your security group of your network (port 443, 22 and 9443 will be open to this) </em></b>
        "sg_cidr": "0.0.0.0/0",

         <b><em>Use private IPs for env deployment (default: no, possible values: yes, no). NB: For AWS If this is set to "yes" and "create_network" is set to "no", you must currently use the DEV CDP CLI.</em></b>
        "use_priv_ips": "no",

        <b><em>Use existing network for env deployment (path to the network file, see examples in parameters_sample) </em></b>
        "existing_network_file": "[path_to_network_file]",

        <b><em>The Data Lake scale you'd like to have (default: LIGHT_DUTY, possible vaules: LIGHT_DUTY, MEDIUM_DUTY_HA) </em></b>
        "scale": "[LIGHT_DUTY]",

        <b><em>If creating an environment with private IPs, create a bastion in one of the public subnets that you can proxy to to access all the UIs. (default: no, possible vaules: no, yes).</em></b>
        "create_bastion": "yes",

        <b><em>Enable workload analytics (i.e. WXM): (default: --no-enable-workload-analytics, possible values: --enable-workload-analytics, --no-enable-workload-analytics) </em></b>
        "workload_analytic": "--enable-workload-analytics",

        <b><em>Array of custom tags to setup (if empty the scripts will generate project, owner, end_date and deploytool tags): </em></b>
        "tags": [
            {
                "key": "my_tag",
                "value": "my_value"
            },
            {
                "key": "my_other_tag",
                "value": "my_other_value"
            }
        ],

    }

}
</pre>

## Parameters file samples

See `parameters_sample` folder


# Doing all the things (full wrapper)

## Creation

Run the source target wrapper script:

```
cdp_create_all_the_things.sh <your_param_file> 
```

## Deletion

Run the deletion script:
```
cdp_delete_all_the_things.sh <your_param_file>
```

# Doing some of the things (individual wrappers)

## AWS things

### Pre-requisites
```
cdp_aws_pre_reqs.sh <your_param_file>
```

### SDX
```
cdp_aws_sdx.sh <your_param_file> [<network_file>]
```


## Azure things

### Pre-requisites
```
cdp_az_pre_reqs.sh <your_param_file>
```

### SDX
```
cdp_az_sdx.sh <your_param_file>
```

## CDP things

### Datahub
```
cdp_create_datahub_things.sh <your_param_file>
```

### CML 
```
cdp_create_ml_things.sh <your_param_file> 
```

### COD 
```
cdp_create_opdb_things.sh <your_param_file> 
```
### CDW 
```
cdp_create_dw_things.sh <your_param_file> 
```


### Starting / Stopping (work in progress)
```
cdp_stop_all_the_things.sh <your_param_file> 
```

```
cdp_start_all_the_things.sh <your_param_file> 
```

# Development Optional flags

Note: some flags require dev cli, not for public consumption, use at your own risk

`--no-cost-check`: removes cost check
`--no-db-ha`: does not create DB HA backend
`--no-sync-users`: does launch sync users to free-ipa

# LiDAR catalog ingestion

Registers one COPC or LAZ tile in `default.lidar_catalog`. Hive/Impala DDL is `lidar-catalog/sql/lidar_catalog.sql`. The job reads header bounds with PDAL (`readers.las`, `count` 0) and appends one row. `--store local` writes that row to a JSON lines file. `--store iceberg` appends with Spark (`spark.sql.extensions` = `org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`, `format("iceberg").mode("append")`) into a local warehouse or an existing Iceberg catalog. Pass an Ozone or S3 URI with `--object-path` when that is the object to record. `--source` is a local path or an `http(s)` tile URL; a failed or empty download stops before any append.

Unit tests use PDAL 2.10.2 metadata fixtures under `lidar-catalog/tests/fixtures/` and a mock `pdal.Pipeline`. Install PDAL (`conda install -c conda-forge pdal`, which provides `python-pdal`) when ingesting a real tile. Set `LIDAR_SAMPLE` to run the live header check.

```bash
cd lidar-catalog
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m lidar_catalog \
  --source /path/to/tile.copc.laz \
  --dataset-source USGS \
  --store local \
  --catalog-path ./lidar_catalog.jsonl
```

```bash
pip install -e ".[dev,iceberg]"
python -m lidar_catalog \
  --source /path/to/tile.copc.laz \
  --dataset-source OpenTopography \
  --object-path ofs://ozone/bucket/lidar/tile.copc.laz \
  --store iceberg \
  --warehouse ./warehouse
```

```bash
pytest
```

Java 17 or newer is required for the local Spark session.

# Flatten points

Unpacks COPC/LAZ points with PDAL into `default.lidar_points`. The table is zstd-compressed Parquet in Iceberg, partitioned by `h3_index`. `default.lidar_catalog` stays the file index: each point stores `file_path`, which joins back to the catalog. Rows keep native X/Y/Z plus WGS84 longitude and latitude, classification, intensity, and return counts. Hive/Impala DDL is `lidar-catalog/sql/lidar_points.sql`.

H3 resolution is **9**. The H3 library's average resolution-9 hexagon is about 0.105 km² with an edge of about 201 m. At a few points per square meter that cell is a large Iceberg partition, and a few-hundred-meter window still touches only a handful of cells. Resolution 8 is about 0.74 km² (edge about 531 m), close to a whole small tile, so partition pruning barely helps. Resolution 10 is about 0.015 km² (edge about 76 m) and multiplies the partition count by seven. The resolution is stored on each row (`h3_resolution`) and as the table property `h3.resolution`.

PDAL copies X/Y/Z, then reprojects to EPSG:4326. On PDAL 2.10.2, reprojected X is longitude and Y is latitude. A tile with no spatial reference is rejected. `--limit` reads the first N points for a small local write. `--store local` writes JSON lines. `--store iceberg` appends with Spark (`spark.sql.extensions` = `org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`, `format("iceberg").mode("append")`).

```bash
python -m lidar_catalog.flatten \
  --source /path/to/tile.copc.laz \
  --dataset-source USGS \
  --store local \
  --points-path ./lidar_points.jsonl \
  --limit 200
```

```bash
python -m lidar_catalog.flatten \
  --source /path/to/tile.copc.laz \
  --dataset-source USGS \
  --object-path ofs://ozone/bucket/lidar/tile.copc.laz \
  --store iceberg \
  --warehouse ./warehouse \
  --limit 200
```

# Bounding-box canopy density

Given a box in the same coordinates as `default.lidar_catalog` (`min_x`, `min_y`, `max_x`, `max_y`), this queries the catalog for intersecting tiles and crops those COPC/LAZ files with PDAL. Canopy points are ASPRS classes 3, 4, and 5. The result is the point counts, the class histogram, and `canopy_density` (canopy points / points inside the crop). The response has no point records. The intersection SQL is `lidar-catalog/sql/lidar_catalog_intersect.sql`. `--store local` reads the JSON lines catalog. `--store iceberg` runs that SQL on `default.lidar_catalog`.

```bash
python -m lidar_catalog.analytics \
  --min-x 635619.85 \
  --min-y 848899.7 \
  --max-x 638982.55 \
  --max-y 853535.43 \
  --store local \
  --catalog-path ./lidar_catalog.jsonl
```

```bash
python -m lidar_catalog.analytics \
  --min-x 635619.85 \
  --min-y 848899.7 \
  --max-x 638982.55 \
  --max-y 853535.43 \
  --store iceberg \
  --warehouse ./warehouse
```

# Future Improvements

* Add support for Azure ML
* Add support for minimal set of policies for AWS
* Add dynamic definition updates 
* Create a nifi flow wrapper?


# Author & Contributors

**Paul Vidal** - [LinkedIn](https://www.linkedin.com/in/paulvid/)

**Dan Chaffelson** - [LinkedIn](https://www.linkedin.com/in/danielchaffey/)

**Chris Perro** - [LinkedIn](https://www.linkedin.com/in/christopher-perro/)

**André Araújo** - [LinkedIn](https://www.linkedin.com/in/asdaraujo/)

**Nathan Anthony** - [LinkedIn](https://www.linkedin.com/in/nateanth/)

**Steffen Maerkl** - [LinkedIn](https://www.linkedin.com/in/steffen-maerkl-0b862650/)

**Mike Riggs** - [LinkedIn](https://www.linkedin.com/in/mriggs/)

**Ryan Cicak** - [LinkedIn](https://www.linkedin.com/in/ryan-cicak-66221a47/)

**Alex Moundalexis** - [LinkedIn](https://www.linkedin.com/in/moundalexis/)
