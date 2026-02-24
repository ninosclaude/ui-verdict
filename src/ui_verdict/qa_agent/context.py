"""
Manyminds context integration for QA-Agent.

Fetches project context from Manyminds to enrich AC verification.
"""
from __future__ import annotations

import os
import httpx
from typing import Any


MANYMINDS_API = os.environ.get("MANYMINDS_API", "https://memories.manyminds.eu")


def fetch_context(project_id: str, query: str) -> dict[str, Any]:
    """Fetch context from Manyminds for a project.
    
    Args:
        project_id: Manyminds project/namespace ID
        query: What to search for (e.g., "notification feature design")
        
    Returns:
        {"context": str, "sources": list[dict]}
    """
    try:
        # Use the recall endpoint
        response = httpx.post(
            f"{MANYMINDS_API}/mcp",
            json={
                "method": "tools/call",
                "params": {
                    "name": "recall",
                    "arguments": {
                        "query": query,
                        "group_ids": [project_id],
                        "max_tokens": 2000,
                    }
                }
            },
            timeout=30.0,
        )
        
        if response.status_code == 200:
            data = response.json()
            memories = data.get("result", {}).get("memories", [])
            
            context_parts = []
            sources = []
            
            for mem in memories:
                content = mem.get("content", "")
                if content:
                    context_parts.append(content)
                    sources.append({
                        "id": mem.get("id"),
                        "source": mem.get("source_description", ""),
                    })
            
            return {
                "context": "\n\n".join(context_parts),
                "sources": sources,
            }
        
        return {"context": "", "sources": []}
        
    except Exception as e:
        return {"context": f"Error fetching context: {e}", "sources": []}


def enrich_story_with_context(story: str, project_id: str | None) -> str:
    """Enrich a user story with project context from Manyminds.
    
    If project_id is provided, fetches relevant context and appends it.
    """
    if not project_id:
        return story
    
    # Extract keywords from story for search
    keywords = " ".join(story.split()[:10])  # First 10 words
    
    result = fetch_context(project_id, keywords)
    
    if result["context"]:
        return f"{story}\n\n--- Project Context ---\n{result['context']}"
    
    return story
