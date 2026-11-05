CREATE TABLE default.lidar_catalog (
    dataset_source STRING,
    file_name STRING,
    file_path STRING,
    min_x DOUBLE,
    min_y DOUBLE,
    max_x DOUBLE,
    max_y DOUBLE,
    point_count BIGINT,
    ingest_timestamp TIMESTAMP
) STORED AS ICEBERG;
