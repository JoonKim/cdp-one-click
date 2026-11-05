-- Files whose catalog box intersects the request.
-- Coordinates match lidar_catalog min_x/min_y/max_x/max_y (the tile CRS).
-- An edge that only touches still counts as an intersection.
SELECT
    dataset_source,
    file_name,
    file_path,
    min_x,
    min_y,
    max_x,
    max_y,
    point_count,
    ingest_timestamp
FROM default.lidar_catalog
WHERE min_x <= {max_x}
  AND max_x >= {min_x}
  AND min_y <= {max_y}
  AND max_y >= {min_y}
