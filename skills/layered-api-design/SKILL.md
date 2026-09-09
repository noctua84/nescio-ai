---
name: layered-api-design
description: Use when building or reviewing an HTTP service in a project that has declared a layered architecture — routing, business, and persistence layers as thin wrappers over focused submodules. Applies only on an explicit project declaration, never inferred from "this is an API". Triggers on "endpoints manager repository", "service layer", "repository pattern", "fat controller", "where does this business logic go", "layered architecture".
user-invocable: true
---

# Layered API design

## The gate — read this before anything else

**This skill applies only when the project has declared a layered service
architecture** in its `CLAUDE.md` `## Architecture` section, or already visibly
uses one (an existing `repositories/` or `services/` tree, layer-named modules,
a documented convention).

**Never infer it from "this is an HTTP API."** Three layers are standard for
CRUD-over-HTTP and actively wrong for a CLI, a batch job, a data pipeline, a
game loop, an event consumer, or a thin proxy. Imposing them where they were not
asked for is the same defect as imposing hexagonal architecture on a script.

If the project has declared no shape, stop here and use the `modular-design`
skill instead — follow the structure that is already there.

## Declaring it

A project opts in with this in its `CLAUDE.md`:

```markdown
## Architecture

Layered service. HTTP handlers validate and format only; managers own the
business rules and the transaction boundary; repositories own SQL.
```

## The three layers

Each layer is a **thin wrapper over focused submodules** — never a single large
file per layer. `managers/billing/` holding `pricing.py` and `invoicing.py`
behind a thin `__init__.py` surface is a layer that has been decomposed. A
2,000-line `managers.py` is a layer that has only been named.

| Layer | Owns | Never touches |
|---|---|---|
| **endpoints** | Parse the request, validate input, call **one** manager function, format the response, map errors to status codes | Business rules, SQL |
| **manager** | Business rules, orchestration across repositories, the transaction boundary | HTTP types in *or* out, SQL |
| **repository** | Persistence; accepts and returns domain types | Business rules |

### Endpoints

An endpoint is a translator between the transport and the domain. It knows what
a 404 is; it does not know why the thing was missing.

Its whole body should read: validate → call one manager function → format. If it
has a branch that is not input validation or error mapping, that branch is a
business rule in the wrong layer.

### Managers

The manager owns the *decisions*. It is where "a refund is allowed within 30
days unless the order shipped" lives. It takes and returns domain types, so the
same function is callable from an HTTP handler, a CLI command, a background job,
or a test — none of which have a `Request` object to hand it.

It also owns the transaction boundary, because it is the only layer that knows
which group of writes must succeed or fail together. A repository that opens its
own transaction per call cannot express that.

### Repositories

The repository owns persistence and nothing else. It accepts and returns domain
types, so the schema can change without the manager changing.

The moment it returns an ORM row, every manager that touches it is coupled to
the schema, and lazy-loading turns a database access into something that can
happen anywhere — including after the transaction closed.

## Anti-patterns

Each has a tell and a fix. Most tells are greppable; two need reading.

- **Fat controller.** Branching business logic in the handler.
  *Tell:* an `if` in an endpoint that is not input validation or error mapping.
  *Fix:* move the decision into a manager function and call it.

- **SQL in the handler.** The repository layer bypassed entirely.
  *Tell:* a query builder, ORM session, or raw SQL imported into a routing module.
  *Fix:* add the repository method the handler wanted.

- **Anemic manager.** A pass-through that only forwards to a repository.
  *Tell:* every method is one line and that line is `return self.repo.x(...)`.
  *Fix:* **delete the layer.** This is the honest signal that this project does
  not need three layers. Keeping an empty layer costs a file, an indirection, and
  a test per call, and buys nothing. Do not invent work for it.

- **Transport leaking down.** HTTP types reaching the business layer.
  *Tell:* `Request`, `Response`, or a status code imported into a manager module.
  *Fix:* the endpoint translates; the manager takes and returns domain types, so
  the same function stays callable from a CLI command, a job, or a test.

- **Leaky repository.** ORM rows returned upward.
  *Tell:* a manager or endpoint importing an ORM model class.
  *Fix:* map to a domain type at the repository boundary.

- **Logic in the serializer.** Business decisions hidden in output formatting.
  *Tell:* a response formatter that computes, filters by rule, or applies
  entitlement.
  *Fix:* the manager returns the decided value; the serializer only shapes it.

- **Handler orchestrating multiple managers.** An endpoint calling two or three
  managers and combining the results.
  *Tell:* more than one manager import in a routing module.
  *Fix:* the missing thing is a manager function that expresses the operation.
  This is a gap in the business layer, not a licence for the handler to coordinate.

## Reviewing an existing service against this

1. Grep routing modules for ORM/SQL imports → SQL in the handler.
2. Grep routing modules for more than one manager import → handler orchestrating
   multiple managers; the missing thing is a manager function.
3. Read each endpoint for a branch that is not input validation or error mapping
   → fat controller.
4. Grep manager modules for HTTP types (`Request`, `Response`, status codes) →
   transport leaking down.
5. Grep manager modules for ORM imports → leaky repository.
6. Read each manager for one-line pass-throughs → anemic manager; the fix is to
   delete the layer.
7. Read response formatters for computation, rule-based filtering, or entitlement
   → logic in the serializer.
8. Run `python scripts/module_scan.py`. A layer file over the tripwire has not
   been decomposed into submodules — apply the `modular-design` skill to it.
