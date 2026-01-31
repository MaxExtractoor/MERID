"""
Automated knowledge article generation service.

Transforms structured incident or feature records into Markdown knowledge base
articles with sections for summary, reproduction, mitigation, and next steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict


@dataclass
class KnowledgeRecord:
    record_id: str
    title: str
    summary: str
    reproduction_steps: str
    mitigation: str
    owner: str
    tags: Dict[str, str]
    created_at: datetime


class KnowledgeArticleGenerator:
    def generate_markdown(self, record: KnowledgeRecord) -> str:
        tags = ", ".join(f"{key}:{value}" for key, value in record.tags.items())
        return f"""# {record.title}

**Record:** {record.record_id}  
**Owner:** {record.owner}  
**Created:** {record.created_at.isoformat()}  
**Tags:** {tags}

## Summary
{record.summary}

## Reproduction Steps
{record.reproduction_steps}

## Mitigation & Resolution
{record.mitigation}

## Follow-Up
- [ ] Validate fix in production
- [ ] Update runbooks
- [ ] Communicate to stakeholders
"""
