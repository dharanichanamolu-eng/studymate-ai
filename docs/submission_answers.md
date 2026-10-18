# Submission answers (DRAFT — edit before submitting)

## Project title
StudyMate AI — An AI Study Assistant with Persistent Memory

## Description (~120 words)
Students often forget what they found difficult, and ordinary chat assistants lose that context between sessions. StudyMate AI is a study assistant for self-learners and students that keeps a persistent memory of their learning. The student describes what they studied, understood, and found difficult, for example "I understand for loops, but nested loops are difficult for me." The app extracts the subject, topics, and difficulty, and stores them as a knowledge graph in FalkorDB. When the student later asks "What should I study next?", the app queries the graph, selects the hardest unresolved topic, explains the choice using the stored memories, and produces a short study plan with practice questions. An optional LLM can phrase the answer; otherwise a clearly labelled rule-based fallback is used.

## Track
**Track 02 — Agent Memory and Coordination.** StudyMate implements persistent, structured agent memory: what the student studied and struggled with survives across sessions and directly changes the assistant's recommendations. It is a single assistant; it does **not** implement multi-agent coordination.

## Repository
https://github.com/dharanichanamolu-eng/studymate-ai

## Demo video
https://youtu.be/ISYEpyCM_S4

Recording checklist: empty fresh student ID → record Python loops session → show saved confirmation and sidebar → ask "What should I study next?" → show retrieved-memory reasoning and plan → explain the graph relationships → be honest about whether the fallback or an LLM answered → under 90 s.

## Live demo or deployment
Not deployed. Runs locally: clone the repo, `pip install -r requirements.txt`, start FalkorDB with `docker run -p 6379:6379 -it --rm falkordb/falkordb:latest`, copy `.env.example` to `.env`, then `streamlit run app.py`. (Replace with a real URL only if you actually deploy and test it.)

## How did you use FalkorDB?
FalkorDB is the application's only memory store. Nodes: `Student`, `Subject`, `Topic`, `StudySession`. Relationships: `(Student)-[:STUDIES]->(Subject)`, `(Subject)-[:CONTAINS]->(Topic)`, `(Student)-[:COMPLETED]->(StudySession)`, `(StudySession)-[:COVERS {outcome, difficulty}]->(Topic)`, `(Student)-[:STRUGGLES_WITH {difficulty, reports, last_reported}]->(Topic)`, and `(Student)-[:UNDERSTANDS]->(Topic)`. Writes use parameterised `MERGE`/`CREATE` queries and unique constraints to avoid duplicates; reporting a topic as understood removes the earlier `STRUGGLES_WITH` edge. Reads retrieve weak topics ordered by difficulty, report count and recency, recent sessions, and a traversal `Student → UNDERSTANDS → Topic ← CONTAINS ← Subject → CONTAINS → weak Topic` to find known topics in the same subject. The retrieved rows are what the recommendation text is built from. All queries start from a student's `sid`, isolating students. The exact queries are listed in the README.

## Blog link (optional)
None published. (Draft not written; skip this field unless you publish one.)

## What did you like about FalkorDB?
As a developer evaluating it for agent memory, I liked that the data model matched the problem: students, topics, and sessions are naturally nodes and edges, and a question like "which topics does this student know in the same subject as the one they struggle with?" is one short Cypher traversal. The Python client was simple to use with parameterised queries, and unique constraints made safe upserts straightforward. Based on this small project only; I have not benchmarked performance or tested scale.

## What improvements would you like to see in FalkorDB?
Possible suggestions, not verified defects: (1) an official, documented pattern or helper for agent-memory use cases (e.g. a sample for session/entity memory); (2) a lightweight embedded or in-process mode that is documented for tests and demos (I used the separate `falkordblite` package for verification); (3) clearer examples of constraint creation order (index first, then constraint) in the Python client docs; (4) more worked examples of `MERGE` with `ON CREATE`/`ON MATCH` and relationship property updates.
