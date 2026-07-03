"""Max Messenger webhook receiver package.

Standalone process that accepts webhook POSTs from the Max API,
stores raw updates in a local SQLite table, and serves them back
to the bot via a GET /updates endpoint using the Max API protocol.
"""
