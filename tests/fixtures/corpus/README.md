# Synthetic test corpus

**This is not guidance and it is not about any real country.** Every task,
artefact and source here is invented to exercise the plan engine. The URLs point
at `example.invalid`, which cannot resolve, so nothing here can be mistaken for a
source.

It exists so that the plan engine tests do not depend on real corpus content.
Reference personas assert exact plans against this corpus, which means curating
the real corpus in M2 cannot break M1's tests, and a change to the engine cannot
be hidden by a change to the content.

What it deliberately contains:

| Shape | Where |
|---|---|
| An alternative route, where one branch is shorter than the other | `permit.apply` requires an address proof **or** a shelter letter |
| A determination gate nobody can clear | `benefit.apply` waits on `determination:residence_test` |
| A waiting period | `work.apply` waits 150 days from arrival |
| A situation-dependent task | `school.enrol` applies only with a child aged 4 to 18 |
| A task whose applicability is unknowable without asking | `id.replace` |
