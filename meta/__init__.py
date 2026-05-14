"""meta — the self-improvement meta-agent (v3).

Reads the episodic eval history, identifies one systematic pattern, proposes
one constrained change, and (chunk 4+) opens a PR. The reward-hacking defense
lives here: a deny-by-default edit surface, rule-based pattern detection (no
LLM cherry-picking), and a propose step blind to the rubric prose it is
optimizing against.
"""
