# 10. Risk and ethics

**Project:** Wayfinder · **Date:** 17 August 2026

Most projects can put this section at the back and treat it as compliance. This
one cannot, because the users are people with very little margin for a system
that is confidently wrong.

---

## 1. Who can be harmed and how

| Harm | Mechanism | Severity | Mitigation |
|---|---|---|---|
| Financial | Somebody plans around a payment they will not receive | High. There is often no buffer | ADR-0004. Determinations are structurally unreachable |
| Legal | An action damages a protection claim | **Severe and sometimes irreversible** | No legal advice, ever. Named alternatives instead |
| Missed emergency | A crisis is not recognised | **Severe** | ADR-0006. Deterministic screen, generous lexicon, 0.99 recall gate |
| Wasted journey | Wrong prerequisite sends somebody across the city | Moderate, and it compounds | Hand-curated corpus, cited prerequisites |
| Stale guidance | Rules changed, the page did not look different | High | ADR-0005. Dated sources, staleness bands |
| Displaced trust | Somebody follows this instead of a caseworker | High | Every refusal names a human. The system positions itself as preparation, not replacement |
| Privacy | Personal circumstances leak | High for this group specifically | No persistence by default, minimal escalation payloads |

The privacy row deserves its own note. For this user group, disclosure of
immigration status or circumstances is not an abstract harm. The design
assumption is that the safest data is the data never stored: situation lives in
graph state for the thread and is purged on completion, and escalations carry
only what the caseworker needs to answer the question.

---

## 2. Where the system must stop

Restated from the PDD because this is the section people check.

- No eligibility determinations.
- No legal advice.
- No outcome predictions.
- No actions taken on anyone's behalf.
- No medical advice.
- No generated content in a crisis response.

Each of these is enforced structurally, not by prompt instruction, and each has a
test.

---

## 3. Failure modes worth naming

**Over-escalation annoying caseworkers into ignoring the queue.** The most likely
way the safety design fails in practice is not by being wrong, but by being so
cautious that the humans stop reading. PDD assumption A4. Needs a real
conversation with an NGO, and it should happen before M6 rather than after.

**Automation bias.** A confident, well-formatted plan invites more trust than a
partial hand-curated corpus deserves. Mitigated by visible citations with dates,
explicit "I do not have a source for this" outcomes, and by not writing in a tone
that projects authority the system does not have.

**Novel crisis phrasing.** The lexicon covers what has been thought of.
Multilingual and non-native phrasing is the weakest area, and stating that is
more useful than claiming coverage.

**The corpus quietly rotting.** Nobody notices a stale corpus by looking at
output. That is why staleness is an operational alarm with an endpoint rather
than a soft flag.

---

## 4. Things this project should not become

Worth writing down now, because each would be an easy and bad next step.

| Tempting | Why not |
|---|---|
| Auto-filling forms | Actions with consequences must stay with the person and their caseworker |
| Predicting case outcomes | Nobody can, and false hope is its own harm |
| Scoring or ranking people | Not our place, and the dataset for it should not exist |
| Sharing data with agencies | The trust model depends entirely on this not happening |
| A general immigration chatbot | The refusal boundary is the product. Removing it removes the point |

---

## 5. If this were ever deployed for real

It is a portfolio project, and the README says so. If it were to go further, none
of the following are optional:

1. Review of the corpus by a qualified adviser, not by the author.
2. A named organisation accountable for the escalation queue, with a real SLA.
3. A published, plain-language description of what the system will not do,
   surfaced in the product rather than buried in documentation.
4. A complaints and correction route for somebody who was given wrong guidance.
5. A data protection assessment, given the population and the categories of data.
6. Independent review of the crisis lexicon by somebody who does this work.
7. An access model for the applicant side. The caseworker queue is behind a
   credential and a determination is signed with the name that credential is
   registered to, which is the part ADR-0004 depends on. But a thread id is
   currently a bearer capability, and the data behind it is what somebody in the
   protection process has disclosed about their own circumstances. For this
   population that is not a routine access-control gap, it is the category of
   data where disclosure can reach the authorities somebody left.

Listing these is not a plan to do them. It is being honest that a demo and a
deployed service are different things, and that the gap between them is mostly
governance rather than code.
