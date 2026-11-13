# HBase data catalog

Catalog of HBase tables as data products. Each table has one security level (`SECRET`, `CUI`, or `UNCLASSIFIED`) and one principal (`user_S`, `user_C`, or `user_U`).

## Open the dashboard

From the repository root:

```
python3 data-catalog/server.py
```

Open http://127.0.0.1:8765 .

The page reads `data-catalog/assignment.json`. That file is written before Ranger policies and Atlas objects are created. The assignment document the operator opens is `docs/hbase-security-assignment.md` in the project store.

## Record and apply

The live CDP control plane is used when the CDP CLI and a profile are configured. This environment had neither, and no cloud CLI credentials, so the apply script targets the reduced cluster in `docker-compose.yml`.

```
python3 data-catalog/scripts/apply_security.py
```

Ranger and Atlas credentials stay in local env files or in process memory. Do not commit them.

## Tests

```
python3 -m unittest discover -s data-catalog/tests -v
```
