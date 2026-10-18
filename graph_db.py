"""FalkorDB data-access layer for StudyMate AI.

All Cypher lives in this file. Every query is parameterised and every
student-facing query starts from `(:Student {sid: $sid})`, so one student's
memories are never returned for another student.
"""
import os
import uuid
from datetime import datetime, timezone

from falkordb import FalkorDB

GRAPH_NAME = os.getenv("FALKORDB_GRAPH", "studymate")

# ---------------------------------------------------------------- Cypher ----
Q_UPSERT_SESSION = """
MERGE (st:Student {sid: $sid})
  ON CREATE SET st.created = $now
MERGE (sub:Subject {name: $subject})
MERGE (st)-[:STUDIES]->(sub)
CREATE (s:StudySession {id: $session_id, date: $now, notes: $notes, subject: $subject})
MERGE (st)-[:COMPLETED]->(s)
"""

Q_COVER_TOPIC = """
MATCH (s:StudySession {id: $session_id}), (sub:Subject {name: $subject})
MERGE (t:Topic {key: $key})
  ON CREATE SET t.name = $topic, t.subject = $subject
MERGE (sub)-[:CONTAINS]->(t)
MERGE (s)-[c:COVERS]->(t)
SET c.outcome = $outcome, c.difficulty = $difficulty
"""

Q_MARK_STRUGGLE = """
MATCH (st:Student {sid: $sid}), (t:Topic {key: $key})
MERGE (st)-[r:STRUGGLES_WITH]->(t)
  ON CREATE SET r.reports = 1, r.first_reported = $now
  ON MATCH SET r.reports = r.reports + 1
SET r.difficulty = $difficulty, r.last_reported = $now
"""

Q_MARK_UNDERSTOOD = """
MATCH (st:Student {sid: $sid}), (t:Topic {key: $key})
MERGE (st)-[u:UNDERSTANDS]->(t)
SET u.last_reported = $now
"""

# Understanding a topic resolves an earlier struggle (the session history stays).
Q_RESOLVE_STRUGGLE = """
MATCH (:Student {sid: $sid})-[r:STRUGGLES_WITH]->(:Topic {key: $key})
DELETE r
"""

Q_WEAK_TOPICS = """
MATCH (:Student {sid: $sid})-[r:STRUGGLES_WITH]->(t:Topic)
RETURN t.name, t.subject, r.difficulty, r.reports, r.last_reported
ORDER BY r.difficulty DESC, r.reports DESC, r.last_reported DESC
"""

Q_UNDERSTOOD_TOPICS = """
MATCH (:Student {sid: $sid})-[u:UNDERSTANDS]->(t:Topic)
RETURN t.name, t.subject, u.last_reported
ORDER BY u.last_reported DESC
"""

Q_RECENT_SESSIONS = """
MATCH (:Student {sid: $sid})-[:COMPLETED]->(s:StudySession)-[c:COVERS]->(t:Topic)
RETURN s.id, s.date, s.notes, t.name, t.subject, c.outcome
ORDER BY s.date DESC
LIMIT $limit
"""

# Graph traversal: other topics of the same subject that the student already understands.
Q_RELATED_UNDERSTOOD = """
MATCH (:Student {sid: $sid})-[:UNDERSTANDS]->(known:Topic)<-[:CONTAINS]-(sub:Subject)-[:CONTAINS]->(weak:Topic {key: $key})
RETURN DISTINCT known.name
"""

Q_STUDENT_GRAPH = """
MATCH (st:Student {sid: $sid})-[:STUDIES]->(sub:Subject)-[:CONTAINS]->(t:Topic)
OPTIONAL MATCH (st)-[r:STRUGGLES_WITH]->(t)
OPTIONAL MATCH (st)-[u:UNDERSTANDS]->(t)
RETURN sub.name, t.name, r IS NOT NULL AS struggling, u IS NOT NULL AS understood
"""

Q_STUDENT_COUNTS = """
MATCH (st:Student {sid: $sid})
OPTIONAL MATCH (st)-[:COMPLETED]->(s:StudySession)
RETURN count(DISTINCT s)
"""

Q_CLEAR_STUDENT = """
MATCH (st:Student {sid: $sid})
OPTIONAL MATCH (st)-[:COMPLETED]->(s:StudySession)
DETACH DELETE s, st
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def topic_key(subject: str, topic: str) -> str:
    return f"{subject.strip().lower()}::{topic.strip().lower()}"


class GraphStore:
    def __init__(self, db=None, graph_name: str = GRAPH_NAME):
        """`db` can be injected (used by tests); otherwise built from env vars."""
        self.db = db or FalkorDB(
            host=os.getenv("FALKORDB_HOST", "localhost"),
            port=int(os.getenv("FALKORDB_PORT", "6379")),
            username=os.getenv("FALKORDB_USERNAME") or None,
            password=os.getenv("FALKORDB_PASSWORD") or None,
            ssl=os.getenv("FALKORDB_SSL", "false").lower() == "true",
            socket_connect_timeout=3,
        )
        self.graph = self.db.select_graph(graph_name)

    # ---- setup / health
    def ping(self) -> None:
        self.graph.query("RETURN 1")

    def ensure_schema(self) -> None:
        """Indexes + uniqueness constraints. Safe to call repeatedly."""
        for label, prop in [("Student", "sid"), ("Subject", "name"),
                            ("Topic", "key"), ("StudySession", "id")]:
            try:
                self.graph.create_node_range_index(label, prop)
            except Exception:
                pass  # index already exists
            try:
                self.graph.create_node_unique_constraint(label, prop)
            except Exception:
                pass  # constraint already exists / pending

    # ---- writes
    def save_session(self, sid: str, parsed: dict, notes: str) -> str:
        """Persist one parsed study report. Returns the session id."""
        session_id = uuid.uuid4().hex
        now = _now()
        subject = parsed["subject"]
        self.graph.query(Q_UPSERT_SESSION, {"sid": sid, "now": now, "subject": subject,
                                            "session_id": session_id, "notes": notes})
        entries = ([(t, "studied", 0) for t in parsed.get("studied", [])]
                   + [(t, "understood", 1) for t in parsed.get("understood", [])]
                   + [(t, "difficult", d) for t, d in parsed.get("difficult", [])])
        for topic, outcome, difficulty in entries:
            key = topic_key(subject, topic)
            p = {"sid": sid, "key": key, "topic": topic, "subject": subject,
                 "session_id": session_id, "outcome": outcome,
                 "difficulty": difficulty, "now": now}
            self.graph.query(Q_COVER_TOPIC, p)
            if outcome == "difficult":
                self.graph.query(Q_MARK_STRUGGLE, p)
            elif outcome == "understood":
                self.graph.query(Q_MARK_UNDERSTOOD, p)
                self.graph.query(Q_RESOLVE_STRUGGLE, p)
        return session_id

    def clear_student(self, sid: str) -> None:
        self.graph.query(Q_CLEAR_STUDENT, {"sid": sid})

    # ---- reads
    def weak_topics(self, sid: str) -> list[dict]:
        rows = self.graph.query(Q_WEAK_TOPICS, {"sid": sid}).result_set
        return [{"topic": r[0], "subject": r[1], "difficulty": r[2],
                 "reports": r[3], "last_reported": r[4]} for r in rows]

    def understood_topics(self, sid: str) -> list[dict]:
        rows = self.graph.query(Q_UNDERSTOOD_TOPICS, {"sid": sid}).result_set
        return [{"topic": r[0], "subject": r[1], "last_reported": r[2]} for r in rows]

    def recent_sessions(self, sid: str, limit: int = 10) -> list[dict]:
        rows = self.graph.query(Q_RECENT_SESSIONS, {"sid": sid, "limit": limit}).result_set
        return [{"session_id": r[0], "date": r[1], "notes": r[2], "topic": r[3],
                 "subject": r[4], "outcome": r[5]} for r in rows]

    def related_understood(self, sid: str, subject: str, topic: str) -> list[str]:
        rows = self.graph.query(Q_RELATED_UNDERSTOOD,
                                {"sid": sid, "key": topic_key(subject, topic)}).result_set
        return [r[0] for r in rows]

    def graph_edges(self, sid: str) -> list[dict]:
        rows = self.graph.query(Q_STUDENT_GRAPH, {"sid": sid}).result_set
        return [{"subject": r[0], "topic": r[1], "struggling": bool(r[2]),
                 "understood": bool(r[3])} for r in rows]

    def session_count(self, sid: str) -> int:
        rows = self.graph.query(Q_STUDENT_COUNTS, {"sid": sid}).result_set
        return int(rows[0][0]) if rows else 0
