"""Platform-specific distribution integrations.

Each module registers itself via ``publish_metrics.register_fetcher``
on import so that ``collect_due_metrics`` picks up real data as soon
as the corresponding credentials are present in the environment.
"""
