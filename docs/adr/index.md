# Architecture Decision Records (ADRs) for KICC / the KI-RefArch

We document all fundamental architectural decisions for our projects as ADRs.
If you don't know if you should create an ADR, the answer is probably "yes".

## ADR List

- [ADR 01: System Architecture](01-system-architecture.md)

## Background

Background information on ADRs:

- [GitHub](https://adr.github.io)
- [Heise](https://www.heise.de/hintergrund/Gut-dokumentiert-Architecture-Decision-Records-4664988.html?seite=all)

## Template

We essentially follow [MADR](https://adr.github.io/madr/), but add a status field.

```
# ADR XX: < short description of the decision >

| Status      | proposed | < accepted | rejected | deprecated | superseded by ADR <n> >
| ----------- | -------- |
| Author      | < initials > |
| Voters      | - |
| Drafted     | < date > |
| Timeline    | tbd |

< optionally reference related ADRs >

## Context and Problem Statement

< explain the context of the decision >

The following criteria are relevant for the decision:

- < criterion a >
- < criterion b >
- < criterion c >

## Considered Options

- x
- y
- z

## Evaluation

### x

- **Criterion a**: < evaluation >
- **Criterion b**: < evaluation >
- **Criterion c**: < evaluation >

< repeat for other options >

## Overview

| Criterion   | Option x | Option y | Option z |
| ----------- | -------- | -------- | -------- |
| Criterion a | ++       | +        | --       |
| Criterion b | -        | ++       | +        |
| Criterion c | +        | +?       | +        |

## Decision Made

< state and justify the decision >

```
