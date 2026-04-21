---
name: memory-first
description: Always check memory before searching the web. Travis's context is already stored.
agents: all
---

# Memory First

Before searching the web or asking Travis for information, CHECK MEMORY.

## Flow

1. **Search memory** for anything related to the task
2. If memory has what you need → use it, don't search the web
3. If memory is incomplete → search web to fill gaps, then store what you learn
4. If memory has nothing → search web, then store important findings

## What's in Memory

Travis has stored:
- His projects (GitHub links, tech stacks, descriptions)
- His skills and experience
- Past conversations and decisions
- Contact info and preferences
- Job search context

## When Travis Says "My Projects"

You already know his projects. Check memory. Don't say "can you tell me your projects?" or "what's your GitHub?"

His GitHub is: https://github.com/angeloasante

Key projects: FRIDAY, Diaspora AI, MineWatch Ghana, Ama Twi AI, Reckall, Kluxta, SendComms, BioFolio.

## When Travis References a Past Conversation

Search memory for the topic. You likely have context from previous sessions. Don't say "I don't have that information" without checking first.

## Learning

When you discover something new about Travis (a new project, skill, preference), store it:
- Use `store_memory` tool
- Category: "project", "personal", "preference", or "general"
- Be specific — include URLs, tech stacks, dates

## Anti-Pattern

NEVER say any of these without checking memory first:
- "I don't have information about your projects"
- "Can you share your GitHub?"
- "What projects have you worked on?"
- "I need more context about your background"

The answer is almost always already in memory. Search it.
