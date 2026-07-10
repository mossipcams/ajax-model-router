---
name: tdd-implementation-packet
description: Create a precise TDD implementation packet for one delegated behavior change after Graphify, Serena, ast-grep, and desired behavior context are available.
---

# TDD Implementation Packet

Use this skill after collecting context from Graphify, Serena, and ast-grep. The output is not a high-level plan. It is an executable packet for an implementation delegate.

## Inputs

Require or reconstruct these inputs before writing the packet:

1. Graphify architecture map
2. Serena semantic code context
3. ast-grep code anchors
4. Desired behavior change

If any input is missing, either gather it or state the missing input as a stop condition. Do not invent architecture boundaries, helpers, or anchors.

## Rules

- Cover one behavior change only.
- Name exact files allowed to change.
- Include the exact test location.
- Include the test case to add.
- Include the production function, method, match arm, branch, or module section to edit.
- Include code anchors from ast-grep.
- Include existing helpers or patterns from Serena that should be reused.
- Include architecture boundaries from Graphify.
- Include forbidden changes.
- Include verification commands.
- Include stop conditions.
- Prefer minimal implementation over cleanup.
- Avoid vague instructions like "make robust", "clean up", "improve", or "refactor" unless converted into exact edits.

## Output Format

Produce exactly these sections:

1. Goal
2. Allowed files
3. Forbidden changes
4. Architecture context
5. Code anchors
6. Test-first instructions
7. Production edit instructions
8. Verification commands
9. Acceptance criteria
10. Stop conditions

## Section Guidance

`Goal`: State the single behavior change in one or two sentences.

`Allowed files`: List only files the delegate may edit. Separate test files from production files.

`Forbidden changes`: Name files, directories, APIs, tests, behaviors, data migrations, generated files, or refactors that are out of scope.

`Architecture context`: Summarize only the boundaries needed for this change. Cite the Graphify-derived module or dependency direction.

`Code anchors`: Include concrete ast-grep patterns and matched symbols/locations. Add Serena-derived helpers, existing tests, constructors, fixtures, or patterns to reuse.

`Test-first instructions`: Name the exact test file and test name. Describe the failing assertion and the focused command that must fail before implementation.

`Production edit instructions`: Name the exact function/branch/module section to edit and the minimal intended logic.

`Verification commands`: Include focused test commands first, then broader commands only when needed.

`Acceptance criteria`: List observable pass conditions, including expected test failure before code and pass after code.

`Stop conditions`: Tell the delegate when to stop and ask for help, such as missing anchors, conflicting architecture boundaries, unexpected test pass before code, failing unrelated tests, or required edits outside the allowed files.
