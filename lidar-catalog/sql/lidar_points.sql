CREATE TABLE default.lidar_points (
    h3_resolution INT,
    x DOUBLE,
    y DOUBLE,
    z DOUBLE,
    longitude DOUBLE,
    latitude DOUBLE,
    classification INT,
    intensity INT,
    return_number INT,
    number_of_returns INT,
    file_path STRING,
    dataset_source STRING,
    ingest_timestamp TIMESTAMP
)
PARTITIONED BY (h3_index BIGINT)
STORED AS ICEBERG
TBLPROPERTIES (
    'write.parquet.compression-codec'='zstd',
    'write.distribution-mode'='hash',
    'h3.resolution'='9'
);
