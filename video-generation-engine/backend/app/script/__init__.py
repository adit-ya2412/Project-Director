"""Script pre-flight (motion_new_styles_and_long_form_videos.md, Track D):
checks a script against a render style BEFORE planning ever runs, at
project setup - not a workflow step, so the run keeps exactly one gate
(the 2026-08-16 one-gate redesign is not reopened).

Two checks, deliberately different in kind (plan §3.1):

- `preflight.py` - feasibility, deterministic, computed from the script's
  character count and the real fragment splitter alone. BLOCKS, because
  it is arithmetic: a shot is at minimum one fragment, so a script
  imposes a hard FLOOR on how fast it can be cut, never a ceiling.
- `suitability.py` - an LLM verdict on tone/subject fit. WARNS, never
  blocks - a model's judgement about someone's own script should never
  be a wall with no argument available.

`styles.py` is the style pacing-band registry both checks read. It is
deliberately NOT `Timeline.metadata.render_style` or any planner-facing
field - Track B's full style/preset system does not exist yet, and this
package must not depend on it landing first (plan §3.5.2).
"""
