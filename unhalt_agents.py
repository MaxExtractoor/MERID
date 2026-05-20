#!/usr/bin/env python3
"""Unhalt all paper session agents to resume trading."""

from merid.prediction.paper_session import get_paper_session

if __name__ == "__main__":
    ps = get_paper_session()
    count = ps.unhalt_all()
    print(f"Unhalted {count} cells")
