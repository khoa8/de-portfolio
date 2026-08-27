# Environment setup

The current verified development environment is macOS on Apple Silicon with
Docker Desktop. The earlier Ubuntu/UTM notes have been retired because they no
longer describe the repository's tested topology.

Use these canonical documents instead:

- [Phase 01 — macOS Docker setup](../docs/runbooks/01-macos-docker-setup.md)
- [Phase 02 — PostgreSQL data layer](../docs/runbooks/02-postgres-data-layer.md)
- [Phase 03 — Airflow setup](../docs/runbooks/03-airflow-setup.md)
- [Portfolio quick start](../README.md#quick-start)

Do not download a generic Airflow Compose file over this repository's reviewed
Compose layers. Do not run destructive volume cleanup during normal setup.
