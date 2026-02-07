"""Lightweight stub for neo4j-backed storage used by legacy modules during tests.

This stub provides a simple in-memory "memory" object to satisfy imports during
unit testing. Replace with a real neo4j adapter or remove the dependency when
those modules are implemented.
"""

memory = {
    "nodes": {},
    "relationships": [],
}


def clear():
    memory["nodes"].clear()
    memory["relationships"].clear()
