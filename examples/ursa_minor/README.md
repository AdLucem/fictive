# Ursa Minor

So the way this works is, 
## AI-Gen
`ursa_minor` is a small multi-actor teacher-support scenario built on
Fictive's interpreter. The assistant persona is **Centaurus**, which helps a
teacher make sense of a lesson plan, compare it with a mock student roster, and
choose what to do next.

`examples/ursa_minor/main.py` starts the scenario with `generator` as the main
actor. That actor mostly acts as a router: it loads the top-level Centaurus
system prompt, calls `lesson_plan_digest`, and then loops so the interaction
keeps returning to the same lesson-planning flow.

`lesson_plan_digest` is the actor that actually carries the conversation. When
it starts, it clears its prior chat history, loads its own system prompt,
generates once from `flics_session.txt` to establish lesson context, and then
stays in a loop of teacher input and follow-up responses. Its prompt tells it
to break the lesson plan into components and ask questions instead of guessing
when something is unclear.

The built-in lesson context models an American history lesson taught through
acting activities. It also includes a mock class roster with named students,
their multiple-intelligence affinities, current needs, recent signals, and
suggested supports. The scenario uses that material to produce classroom-ready
next steps and targeted teaching support.

Two helper actors provide alternate views of the same lesson output:

- `action_steps_formatter` reformats the latest `generator` output into a
  classroom-ready action plan.
- `logical_mathematical` reframes the latest `generator` output through a
  logical-mathematical multiple-intelligences lens.

So in practice, Ursa Minor is mainly an interactive lesson-plan intake and
clarification workflow, with extra helper actors available for focused
reformatting or adaptation. `sample_lesson_plan.md` is a handy example input
for trying the scenario.
