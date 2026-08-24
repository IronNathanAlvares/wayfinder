/* Wayfinder demo site.
 *
 * Every value that reaches the page goes through textContent rather than
 * innerHTML. The data file is generated from the real system so it is not
 * hostile input, but a page that claims to be careful about security should not
 * have an HTML sink in it at all. The only markup this file writes is the SVG
 * it builds node by node.
 *
 * No network requests. The data arrives as window.WAYFINDER from data.js, which
 * is what lets the Content-Security-Policy set connect-src 'none'.
 */
(function () {
  "use strict";

  var D = window.WAYFINDER;
  if (!D) return;

  /* ── tiny DOM helpers ───────────────────────────────────────────────── */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  var SVG_NS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    return node;
  }

  /* Status icons. These exist so state is never carried by colour alone: a
     reader who cannot distinguish the hues still gets a distinct shape and the
     word next to it. */
  var ICONS = {
    ready: "M20 6L9 17l-5-5",
    waiting: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    external: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 7a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm13 14v-2a4 4 0 0 0-3-3.87",
    crisis: "M12 9v4m0 4h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z",
    done: "M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3",
    /* An hourglass for a window that is running, and the same alert triangle
       the crisis chip uses for one that may already have run out. The chip
       always carries an icon and a word as well as a colour, because "closing"
       against "open" is exactly the red/amber pair a colour-blind reader
       loses first. */
    "deadline-open": "M6 2h12M6 22h12M6 2v6l6 4 6-4V2M6 22v-6l6-4 6 4v6",
    "deadline-unknown_start": "M6 2h12M6 22h12M6 2v6l6 4 6-4V2M6 22v-6l6-4 6 4v6",
    "deadline-closing": "M6 2h12M6 22h12M6 2v6l6 4 6-4V2M6 22v-6l6-4 6 4v6",
    "deadline-may_have_closed":
      "M12 9v4m0 4h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z"
  };

  function chip(kind, label) {
    var span = el("span", "chip chip-" + kind);
    var s = svg("svg", {
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "2.4",
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
      focusable: "false"
    });
    s.appendChild(svg("path", { d: ICONS[kind] || ICONS.waiting }));
    span.appendChild(s);
    span.appendChild(el("span", null, label));
    return span;
  }

  /* ── theme ──────────────────────────────────────────────────────────── */

  (function theme() {
    var KEY = "wayfinder-theme";
    var button = document.getElementById("theme");
    var label = document.getElementById("theme-label");
    var order = ["auto", "light", "dark"];
    var names = { auto: "Auto", light: "Light", dark: "Dark" };

    var current = "auto";
    try {
      var saved = window.localStorage.getItem(KEY);
      if (order.indexOf(saved) !== -1) current = saved;
    } catch (e) {
      /* Private mode, or storage disabled. Auto is a fine answer. */
    }

    /* ?theme=dark wins over the stored choice, so a link can carry a theme and
       a screenshot can capture the same page a visitor sees rather than a mode
       that only exists for cameras. Not persisted: a shared link should not
       silently change what somebody's next visit looks like. */
    var asked = (/[?&]theme=([a-z]+)/.exec(window.location.search) || [])[1];
    if (order.indexOf(asked) !== -1) current = asked;

    function apply() {
      if (current === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", current);
      label.textContent = names[current];
      button.setAttribute(
        "aria-label",
        "Colour theme: " + names[current] + ". Activate to change."
      );
    }

    button.addEventListener("click", function () {
      current = order[(order.indexOf(current) + 1) % order.length];
      try {
        window.localStorage.setItem(KEY, current);
      } catch (e) {
        /* Nothing to do. The choice just will not persist. */
      }
      apply();
    });

    apply();
  })();

  /* ── the hero's artefact ────────────────────────────────────────────── */

  (function heroDemo() {
    var host = document.getElementById("hero-demo");
    if (!host) return;

    var turn = null;
    for (var i = 0; i < D.turns.length; i++) {
      if (D.turns[i].route === "determination") turn = D.turns[i];
    }
    if (!turn || !turn.escalation) return;

    host.appendChild(chip("external", "Determination"));
    host.appendChild(el("p", "asked", "“" + turn.question + "”"));
    host.appendChild(
      el("p", "verdict",
        "Not answered, and nothing was generated. The graph stopped and handed " +
        "it to a person. This is what reached her queue:")
    );

    var payload = el("pre", "payload");
    payload.textContent = turn.escalation.situationSummary;
    host.appendChild(payload);

    var who = el("p", "who");
    who.appendChild(el("span", null, "Waiting on " + D.handoff.caseworker));
    host.appendChild(who);
  })();

  /* ── hero statistics ────────────────────────────────────────────────── */

  (function heroStats() {
    var host = document.getElementById("hero-stats");
    if (!host) return;

    var opus = D.measurements.arms[D.measurements.arms.length - 1];
    var stats = [
      { label: "Tasks in the Irish corpus", value: String(D.corpusHealth.tasks), unit: "across four domains" },
      { label: "Sources, every one dated", value: String(D.corpusHealth.sources), unit: "checked " + D.corpusHealth.checkedOn },
      { label: "Crisis recall, held out", value: opus.recall.toFixed(3), unit: "on " + opus.of + " turns" },
      { label: "Tests", value: "571", unit: "mypy strict, 4 contracts" }
    ];

    stats.forEach(function (s) {
      var wrapper = el("div", "stat");
      wrapper.appendChild(el("dt", null, s.label));
      var dd = el("dd");
      dd.appendChild(el("span", null, s.value));
      dd.appendChild(document.createTextNode(" "));
      dd.appendChild(el("span", "unit", s.unit));
      wrapper.appendChild(dd);
      host.appendChild(wrapper);
    });
  })();

  /* ── the plan ───────────────────────────────────────────────────────── */

  (function planSection() {
    var columns = document.getElementById("plan-columns");
    var questions = document.getElementById("plan-questions");
    var diffBox = document.getElementById("plan-diff");
    var tabs = Array.prototype.slice.call(
      document.querySelectorAll(".tabs button[data-plan]")
    );
    if (!columns) return;

    function deadlineLabel(deadline) {
      if (deadline.status === "may_have_closed") return "time limit: check the date";
      if (deadline.status === "closing") return "time limit: closing";
      if (deadline.status === "unknown_start") return "time limit applies";
      return "time limit";
    }

    function taskCard(task, kind) {
      var button = el("button", "task");
      button.type = "button";
      button.setAttribute("aria-expanded", "false");

      button.appendChild(el("span", "task-title", task.title));

      var meta = el("span", "task-meta");
      /* A closing window goes in the meta row, first, in both columns. It is
         the one fact on a card that can stop being true, and it never says a
         window has shut: `may_have_closed` is the strongest status there is,
         and the sentence comes from the same renderer the CLI uses so the two
         cannot drift apart. */
      if (task.deadline) {
        meta.appendChild(chip("deadline-" + task.deadline.status, deadlineLabel(task.deadline)));
      }
      if (kind === "ready") {
        if (task.unblocks > 0) {
          meta.appendChild(
            el("span", null, "unblocks " + task.unblocks +
              (task.unblocks === 1 ? " other task" : " other tasks"))
          );
        }
        if (task.gatesDays > 0) {
          /* gated_wait is the longest downstream wait this task gates, not a
             wait for the task itself. Saying "wait once started" reversed it,
             and reversing it loses the whole point: this is the number that
             says do it first because a long clock begins after it. */
          meta.appendChild(
            el("span", null, "starts a " + task.gatesDays + " day clock downstream")
          );
        }
      } else if (kind === "waiting") {
        if (task.doFirst && task.doFirst.length) {
          meta.appendChild(el("span", null, "do first: " + task.doFirst.join(", ")));
        }
        (task.decidedElsewhere || []).forEach(function (ref) {
          meta.appendChild(chip("external", "decided by " + ref.split(":")[1].replace(/_/g, " ")));
        });
      }
      if (meta.childNodes.length) button.appendChild(meta);

      var why = el("span", "task-why");
      why.hidden = true;
      /* The full sentence, above `why`, because it is the part that expires. */
      if (task.deadline) {
        why.appendChild(el("p", "task-deadline", task.deadline.line));
      }
      if (task.why) why.appendChild(el("p", null, task.why));
      if (kind === "waiting" && task.decidedElsewhere && task.decidedElsewhere.length) {
        why.appendChild(
          el("p", null,
            "This one is not refused and not granted. It is waiting on a decision " +
            "that a named authority makes, and nothing in this system decides it.")
        );
      }
      button.appendChild(why);

      button.addEventListener("click", function () {
        var open = button.getAttribute("aria-expanded") === "true";
        button.setAttribute("aria-expanded", open ? "false" : "true");
        why.hidden = open;
      });
      return button;
    }

    function column(kind, heading, items, render) {
      var box = el("div", "column");
      var head = el("div", "column-head");
      head.appendChild(chip(kind, heading));
      head.appendChild(el("span", "count", String(items.length)));
      box.appendChild(head);

      var body = el("div", "column-body");
      if (!items.length) {
        body.appendChild(el("p", "note", "Nothing here yet."));
      } else {
        items.forEach(function (item) { body.appendChild(render(item)); });
      }
      box.appendChild(body);
      return box;
    }

    function draw(which) {
      var plan = D.plans[which];
      clear(columns);

      columns.appendChild(
        column("ready", "Can start now", plan.startNow, function (t) {
          return taskCard(t, "ready");
        })
      );
      columns.appendChild(
        column("waiting", "Waiting on something", plan.waiting, function (t) {
          return taskCard(t, "waiting");
        })
      );
      columns.appendChild(
        column("done", "Already done", plan.done, function (t) {
          var b = el("div", "task");
          b.appendChild(el("span", "task-title", t.title));
          return b;
        })
      );

      clear(questions);
      if (plan.openQuestions.length) {
        questions.appendChild(
          el("p", null,
            "Genuinely unknown, so it asks rather than assuming. Three-valued " +
            "logic: a fact that is neither held nor known to be absent is not " +
            "treated as false.")
        );
        var list = el("ul");
        plan.openQuestions.forEach(function (q) {
          list.appendChild(el("li", null, q.replace(/_/g, " ").replace(":", ": ")));
        });
        questions.appendChild(list);
      } else {
        questions.appendChild(
          el("p", null,
            "Nothing is unknown at this point. Every fact the applicable tasks " +
            "depend on is recorded as either held or absent.")
        );
      }

      clear(diffBox);
      if (which === "sixWeeksLater") {
        diffBox.hidden = false;
        diffBox.appendChild(el("h3", null, "What changed in six weeks"));
        var groups = [
          ["You can now start", D.diff.nowStartable],
          ["New on your list", D.diff.newlyApplicable],
          ["Now done", D.diff.nowDone]
        ];
        groups.forEach(function (pair) {
          if (!pair[1].length) return;
          diffBox.appendChild(el("p", null, pair[0] + ":"));
          var ul = el("ul");
          pair[1].forEach(function (title) { ul.appendChild(el("li", null, title)); });
          diffBox.appendChild(ul);
        });
      } else {
        diffBox.hidden = true;
      }
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (other) {
          other.setAttribute("aria-selected", String(other === tab));
        });
        document
          .getElementById("panel-plan")
          .setAttribute("aria-labelledby", tab.id);
        draw(tab.getAttribute("data-plan"));
      });
    });

    draw("weekOne");
  })();

  /* ── ask it ─────────────────────────────────────────────────────────── */

  (function askSection() {
    var list = document.getElementById("ask-list");
    var panel = document.getElementById("ask-panel");
    if (!list || !panel) return;

    var ROUTES = {
      procedural: { chip: "ready", label: "Procedural", verdict: "Answered, with every source dated." },
      planning: { chip: "ready", label: "Planning", verdict: "A plan is built before anything is written." },
      determination: { chip: "external", label: "Determination", verdict: "Not answered. Paused for a named caseworker." },
      crisis: { chip: "crisis", label: "Crisis", verdict: "Terminal. Read from a dated directory, no model involved." },
      out_of_scope: { chip: "waiting", label: "Out of scope", verdict: "Declined, and it names somebody who can help." }
    };

    function show(turn, button) {
      Array.prototype.forEach.call(list.children, function (child) {
        child.setAttribute("aria-selected", String(child === button));
      });

      clear(panel);
      var route = ROUTES[turn.route] || ROUTES.procedural;

      var head = el("div", "route-line");
      head.appendChild(chip(route.chip, route.label));
      head.appendChild(el("span", "verdict", route.verdict));
      panel.appendChild(head);

      if (turn.paused) {
        panel.appendChild(
          el("p", "answer",
            "The graph stopped here. Nothing was generated. This is what reached " +
            "the caseworker queue:")
        );
        var payload = el("pre", "payload");
        payload.textContent =
          "asked: " + turn.escalation.question + "\n" +
          "on:    " + turn.escalation.askedOn + "\n\n" +
          turn.escalation.situationSummary;
        panel.appendChild(payload);
      } else {
        var answer = el("p", "answer" + (turn.route === "crisis" ? " is-crisis" : ""));
        answer.textContent = turn.answer;
        panel.appendChild(answer);

        if (turn.citations && turn.citations.length) {
          var cites = el("div", "cites");
          cites.appendChild(el("h3", null, "Sources behind that answer"));
          turn.citations.forEach(function (c) {
            var box = el("div", "cite");
            box.appendChild(el("span", "cite-title", c.title));
            var meta = el("span", "cite-meta");
            meta.appendChild(el("span", null, c.source));
            meta.appendChild(el("span", null, "checked " + c.lastVerified));
            /* Bare "status" or "banking" next to a date reads as a stray
               word. Naming it is the point anyway: retrieval is scoped to one
               domain so a banking answer cannot cite a healthcare source. */
            meta.appendChild(el("span", null, "domain: " + c.domain));
            box.appendChild(meta);
            var link = el("a", null, c.url);
            link.href = c.url;
            link.rel = "noopener noreferrer nofollow";
            box.appendChild(link);
            cites.appendChild(box);
          });
          panel.appendChild(cites);
        } else if (turn.route !== "crisis") {
          panel.appendChild(
            el("p", "note",
              "No sources are attached, because nothing here is a claim about " +
              "the world that would need one.")
          );
        }
      }

      if (turn.trace && turn.trace.length) {
        var details = el("details", "trace");
        details.appendChild(el("summary", null, "Why it did that, step by step"));
        var ol = el("ol");
        turn.trace.forEach(function (step) {
          var li = el("li");
          li.appendChild(el("span", "node", step.node));
          li.appendChild(document.createTextNode(" — " + step.detail));
          ol.appendChild(li);
        });
        details.appendChild(ol);
        panel.appendChild(details);
      }
    }

    D.turns.forEach(function (turn, index) {
      var button = el("button", "ask-item");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(index === 0));
      var route = ROUTES[turn.route] || ROUTES.procedural;
      button.appendChild(chip(route.chip, route.label));
      button.appendChild(el("span", "ask-q", "“" + turn.question + "”"));
      button.addEventListener("click", function () { show(turn, button); });
      list.appendChild(button);
      if (index === 0) show(turn, button);
    });
  })();

  /* ── handoff ────────────────────────────────────────────────────────── */

  (function handoffSection() {
    var host = document.getElementById("handoff-flow");
    if (!host) return;
    var h = D.handoff;

    function step(n, title, description, build) {
      var box = el("article", "step");
      box.appendChild(el("span", "step-num", "STEP " + n));
      box.appendChild(el("h3", null, title));
      box.appendChild(el("p", null, description));
      if (build) build(box);
      return box;
    }

    host.appendChild(
      step(1, "It stops", "An entitlement question never reaches generation. The pause is written to disk under a thread id.", function (box) {
        var pre = el("pre", "payload");
        pre.textContent = "asked: " + h.queueItem.asked + "\non:    " + h.queueItem.askedOn;
        box.appendChild(pre);
      })
    );

    host.appendChild(
      step(2, "Clare sees it", "The queue carries the question and a short summary of the situation. Not the whole file.", function (box) {
        var pre = el("pre", "payload");
        pre.textContent = h.queueItem.situationSummary;
        box.appendChild(pre);
      })
    );

    host.appendChild(
      step(3, "She answers, and it is hers", "Relayed rather than restated, and attributed. The system adds nothing.", function (box) {
        var reply = el("div", "reply");
        reply.textContent = h.reply;
        box.appendChild(reply);
        box.appendChild(chip("external", h.attributedTo));
      })
    );
  })();

  /* ── topology ───────────────────────────────────────────────────────── */

  (function topologySection() {
    var host = document.getElementById("topology");
    if (!host) return;

    /* Laid out in columns by hand; the edges are the real ones from the
       compiled graph, so a route that changes shows up as a wrong-looking
       arrow rather than as nothing. */
    var COLUMN = {
      __start__: 0, intake: 1, classify: 1, supervisor: 2, crisis: 2,
      handoff: 2, decline: 2, plan: 3, retrieve: 3, compose: 4,
      verify: 5, plain: 6, __end__: 7
    };
    var LABEL = {
      __start__: "start", __end__: "end", classify: "classify", crisis: "crisis",
      handoff: "handoff", decline: "decline", intake: "intake",
      supervisor: "supervisor", retrieve: "retrieve", plan: "plan",
      compose: "compose", verify: "verify", plain: "plain"
    };
    var HIGHLIGHT = { crisis: "crisis", handoff: "external", compose: "ready" };

    var byColumn = {};
    D.topology.nodes.forEach(function (name) {
      var c = COLUMN[name] === undefined ? 3 : COLUMN[name];
      (byColumn[c] = byColumn[c] || []).push(name);
    });

    var COL_W = 108, ROW_H = 52, PAD = 16, BOX_W = 88, BOX_H = 28;
    var maxRows = 1;
    Object.keys(byColumn).forEach(function (c) {
      maxRows = Math.max(maxRows, byColumn[c].length);
    });

    var width = (Math.max.apply(null, Object.keys(COLUMN).map(function (k) {
      return COLUMN[k];
    })) + 1) * COL_W + PAD * 2;
    var height = maxRows * ROW_H + PAD * 2;

    var pos = {};
    Object.keys(byColumn).forEach(function (c) {
      var names = byColumn[c].slice().sort();
      names.forEach(function (name, i) {
        var offset = (maxRows - names.length) * ROW_H / 2;
        pos[name] = {
          x: PAD + Number(c) * COL_W,
          y: PAD + offset + i * ROW_H
        };
      });
    });

    var root = svg("svg", {
      viewBox: "0 0 " + width + " " + height,
      role: "img",
      "aria-label":
        "The compiled graph. Determination questions reach composition only " +
        "through the handoff node; the crisis and decline nodes end the turn."
    });

    var defs = svg("defs", {});
    var marker = svg("marker", {
      id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
      markerWidth: "5", markerHeight: "5", orient: "auto-start-reverse"
    });
    marker.appendChild(svg("path", { d: "M0 0 10 5 0 10z", fill: "currentColor" }));
    defs.appendChild(marker);
    root.appendChild(defs);

    var edges = svg("g", { stroke: "currentColor", "stroke-width": "1.2", fill: "none", opacity: "0.45" });
    D.topology.edges.forEach(function (e) {
      var a = pos[e.from], b = pos[e.to];
      if (!a || !b) return;
      var x1 = a.x + BOX_W, y1 = a.y + BOX_H / 2;
      var x2 = b.x, y2 = b.y + BOX_H / 2;
      var mid = (x1 + x2) / 2;
      edges.appendChild(
        svg("path", {
          d: "M" + x1 + " " + y1 + " C" + mid + " " + y1 + " " + mid + " " + y2 + " " + x2 + " " + y2,
          "marker-end": "url(#arrow)"
        })
      );
    });
    root.appendChild(edges);

    D.topology.nodes.forEach(function (name) {
      var p = pos[name];
      if (!p) return;
      var group = svg("g", {});
      var kind = HIGHLIGHT[name];
      group.appendChild(
        svg("rect", {
          x: p.x, y: p.y, width: BOX_W, height: BOX_H, rx: 7,
          fill: kind ? "var(--" + kind + "-soft)" : "var(--surface)",
          stroke: kind ? "var(--" + kind + ")" : "var(--line-strong)",
          "stroke-width": kind ? 1.6 : 1
        })
      );
      var text = svg("text", {
        x: p.x + BOX_W / 2, y: p.y + BOX_H / 2 + 4,
        "text-anchor": "middle",
        "font-size": "11",
        "font-family": "ui-monospace, monospace",
        fill: kind ? "var(--" + kind + ")" : "var(--ink)"
      });
      text.textContent = LABEL[name] || name;
      group.appendChild(text);
      root.appendChild(group);
    });

    host.appendChild(root);
  })();

  /* ── measurements chart ─────────────────────────────────────────────── */

  (function chartSection() {
    var host = document.getElementById("chart");
    if (!host) return;
    var m = D.measurements;

    m.arms.forEach(function (arm) {
      var row = el("div", "bar-row");

      var head = el("div", "bar-head");
      head.appendChild(el("span", "bar-name", arm.label));
      head.appendChild(el("span", "bar-model", arm.model));
      head.appendChild(el("span", "bar-value", arm.recall.toFixed(3)));
      row.appendChild(head);

      var track = el("div", "bar-track");
      var fill = el("div", "bar-fill");
      fill.style.width = (arm.recall * 100).toFixed(1) + "%";
      track.appendChild(fill);

      var bound = el("div", "bar-bound");
      bound.style.left = (arm.bound * 100).toFixed(1) + "%";
      track.appendChild(bound);

      var gate = el("div", "bar-gate");
      gate.style.left = (m.gate * 100).toFixed(1) + "%";
      track.appendChild(gate);
      row.appendChild(track);

      var foot = el("div", "bar-foot");
      foot.appendChild(el("span", null, arm.caught + " of " + arm.of + " caught"));
      foot.appendChild(el("span", null, "95% lower bound " + arm.bound.toFixed(3)));
      foot.appendChild(
        el("span", null, arm.falsePositives + " of " + m.nearMisses + " near misses fired")
      );
      row.appendChild(foot);

      host.appendChild(row);
    });

    var legend = el("div", "legend");
    [
      ["key key-fill", "Observed recall"],
      ["key key-bound", "95% lower bound, the number to read"],
      ["key key-gate", "The 0.99 target, still unmet"]
    ].forEach(function (pair) {
      var span = el("span");
      span.appendChild(el("i", pair[0]));
      span.appendChild(el("span", null, pair[1]));
      legend.appendChild(span);
    });
    host.appendChild(legend);
  })();

  /* ── the misses that remain ─────────────────────────────────────────── */

  (function missesSection() {
    var host = document.getElementById("misses");
    if (!host) return;

    var intro = el("p", "note");
    intro.textContent =
      "None of these are self-harm, which is the change that matters. They are " +
      "bureaucratic catch-22s and children who are unregistered rather than " +
      "unsafe, and several are defensibly not emergencies tonight.";
    host.appendChild(intro);

    var list = el("div", "miss-list");
    D.measurements.opusMisses.forEach(function (miss) {
      var row = el("div", "miss");
      row.appendChild(el("span", "cat", miss.category.replace(/_/g, " ")));
      row.appendChild(el("span", null, "“" + miss.text + "”"));
      list.appendChild(row);
    });
    host.appendChild(list);
  })();

  /* ── footer note ────────────────────────────────────────────────────── */

  (function footNote() {
    var host = document.getElementById("foot-note");
    if (!host) return;
    host.textContent =
      "Recorded from the system on " + D.today +
      ". Regenerated by scripts/build_site_data.py, and a test fails if this " +
      "page and the code ever disagree.";
  })();
})();
