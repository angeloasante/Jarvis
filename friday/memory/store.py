"""FRIDAY Memory System — ChromaDB (semantic) + SQLite (structured).

Memory is what makes FRIDAY FRIDAY. Without it she's a chatbot in a costume.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb

from friday.core.config import SQLITE_DB_PATH, CHROMA_PERSIST_DIR
from friday.core.types import ToolResult


class MemoryStore:
    def __init__(self):
        self._init_sqlite()
        self._init_chroma()

    def _init_sqlite(self):
        self.db = sqlite3.connect(str(SQLITE_DB_PATH), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                importance INTEGER DEFAULT 5
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                summary TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                agent TEXT NOT NULL,
                tool TEXT,
                args TEXT,
                result_summary TEXT,
                success INTEGER,
                duration_ms INTEGER,
                called_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS monitors (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                monitor_type TEXT NOT NULL,
                target TEXT NOT NULL,
                frequency TEXT NOT NULL,
                importance TEXT NOT NULL DEFAULT 'normal',
                keywords TEXT DEFAULT '[]',
                content_hash TEXT,
                last_content TEXT,
                last_checked TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id TEXT NOT NULL,
                change_summary TEXT,
                diff TEXT,
                is_material INTEGER DEFAULT 0,
                detected_at TEXT NOT NULL,
                delivered INTEGER DEFAULT 0,
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS briefing_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                queued_at TEXT NOT NULL,
                delivered INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                description TEXT,
                url TEXT,
                language TEXT,
                all_languages TEXT DEFAULT '[]',
                topics TEXT DEFAULT '[]',
                private INTEGER DEFAULT 0,
                stars INTEGER DEFAULT 0,
                forks INTEGER DEFAULT 0,
                open_issues INTEGER DEFAULT 0,
                open_prs INTEGER DEFAULT 0,
                default_branch TEXT DEFAULT 'main',
                readme_summary TEXT,
                tech_stack TEXT,
                status TEXT DEFAULT 'active',
                synced_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_agent_calls_session ON agent_calls(session_id);
            CREATE INDEX IF NOT EXISTS idx_monitors_active ON monitors(active);
            CREATE INDEX IF NOT EXISTS idx_monitor_events_monitor ON monitor_events(monitor_id);
            CREATE INDEX IF NOT EXISTS idx_briefing_queue_delivered ON briefing_queue(delivered);
            CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
        """)
        self.db.commit()

    def _init_chroma(self):
        self.chroma = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.collection = self.chroma.get_or_create_collection(
            name="friday_memories",
            metadata={"hnsw:space": "cosine"},
        )

    def store(self, content: str, category: str = "general", tags: list[str] | None = None, importance: int = 5) -> str:
        """Store a memory in both SQLite and ChromaDB."""
        mem_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags = tags or []

        # SQLite
        self.db.execute(
            "INSERT INTO memories (id, content, category, tags, created_at, updated_at, importance) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mem_id, content, category, json.dumps(tags), now, now, importance),
        )
        self.db.commit()

        # ChromaDB for semantic search
        self.collection.add(
            ids=[mem_id],
            documents=[content],
            metadatas=[{"category": category, "tags": json.dumps(tags), "importance": importance}],
        )

        return mem_id

    def search(self, query: str, n_results: int = 5, category: Optional[str] = None) -> list[dict]:
        """Semantic search over memories."""
        where = {"category": category} if category else None
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )

        memories = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                memories.append({
                    "id": results["ids"][0][i],
                    "content": doc,
                    "category": meta.get("category", ""),
                    "distance": results["distances"][0][i] if results["distances"] else None,
                })
        return memories

    def get_by_category(self, category: str, limit: int = 10) -> list[dict]:
        """Get memories by category from SQLite."""
        rows = self.db.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (category, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get most recent memories."""
        rows = self.db.execute(
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def log_agent_call(self, session_id: str, agent: str, tool: str, args: dict, result_summary: str, success: bool, duration_ms: int):
        """Log an agent tool call for debugging and reflection."""
        self.db.execute(
            "INSERT INTO agent_calls (session_id, agent, tool, args, result_summary, success, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, agent, tool, json.dumps(args, default=str), result_summary, int(success), duration_ms),
        )
        self.db.commit()

    def get_recent_agent_calls(self, limit: int = 5) -> list[dict]:
        """Get most recent agent dispatch records."""
        rows = self.db.execute(
            "SELECT agent, tool, result_summary, success, duration_ms, called_at "
            "FROM agent_calls ORDER BY called_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Project methods ──────────────────────────────────────────────────

    def upsert_project(self, project: dict):
        """Insert or update a project record."""
        self.db.execute(
            """INSERT INTO projects (name, description, url, language, all_languages,
                topics, private, stars, forks, open_issues, open_prs,
                default_branch, readme_summary, tech_stack, status, synced_at,
                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description, url=excluded.url,
                language=excluded.language, all_languages=excluded.all_languages,
                topics=excluded.topics, private=excluded.private,
                stars=excluded.stars, forks=excluded.forks,
                open_issues=excluded.open_issues, open_prs=excluded.open_prs,
                default_branch=excluded.default_branch,
                readme_summary=excluded.readme_summary,
                tech_stack=excluded.tech_stack, status=excluded.status,
                synced_at=datetime('now'), updated_at=excluded.updated_at""",
            (
                project["name"], project.get("description", ""),
                project.get("url", ""), project.get("language", ""),
                json.dumps(project.get("all_languages", [])),
                json.dumps(project.get("topics", [])),
                int(project.get("private", False)),
                project.get("stars", 0), project.get("forks", 0),
                project.get("open_issues", 0), project.get("open_prs", 0),
                project.get("default_branch", "main"),
                project.get("readme_summary", ""),
                project.get("tech_stack", ""),
                project.get("status", "active"),
                project.get("created_at", ""),
                project.get("updated_at", ""),
            ),
        )
        self.db.commit()

    def get_all_projects(self) -> list[dict]:
        """Get all projects ordered by last updated."""
        rows = self.db.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_project(self, name: str) -> dict | None:
        """Get a single project by name."""
        row = self.db.execute(
            "SELECT * FROM projects WHERE name = ?", (name,),
        ).fetchone()
        return dict(row) if row else None

    def get_project_context(self, limit: int = 10) -> str:
        """Build a compact project context string for the system prompt.

        Only includes the top N most recently updated repos.
        Keeps descriptions short to minimize prompt tokens.
        """
        projects = self.get_all_projects()[:limit]
        if not projects:
            return ""

        lines = ["TRAVIS'S PROJECTS (top repos):"]
        for p in projects:
            lang = p.get("language") or "?"
            desc = (p.get("description") or "")[:80]
            line = f"- {p['name']} ({lang}): {desc}"
            lines.append(line)

        return "\n".join(lines)

    def build_context(self, query: str = "") -> str:
        """Build memory context string for injection into system prompt.

        Only injects preferences and person/decision memories — NOT general facts
        from old conversations, which contaminate responses with stale info
        (e.g. Neuralink facts bleeding into Halo glasses questions).
        """
        sections = []

        # User preferences and decisions (useful for personalisation)
        USEFUL_CATEGORIES = ("preference", "person", "decision")
        recent = self.get_recent(5)
        useful = [m for m in recent if m.get("category") in USEFUL_CATEGORIES]
        if useful:
            sections.append("CONTEXT:")
            for m in useful:
                sections.append(f"- {m['content']}")

        if not sections:
            return ""

        return "\n".join(sections)


# Singleton
_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
