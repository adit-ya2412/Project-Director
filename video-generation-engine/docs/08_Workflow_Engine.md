# Workflow Engine

**Version:** 1.0

---

# Purpose

The Workflow Engine orchestrates the execution of the Video Generation Engine.

It is responsible for coordinating planners, deterministic services, retries, and workflow state.

It does **not** contain business logic.

---

# Responsibilities

- Execute workflows
- Maintain project state
- Execute workflow steps
- Retry failures
- Publish events
- Track progress

---

# Workflow

```
Project Created

↓

Generate Timeline

↓

User Approval

↓

Plan Assets

↓

Resolve Assets

↓

Generate Missing Media

↓

Render Video

↓

Completed
```

---

# Workflow Steps

## Step 1

Generate Timeline

Output

Timeline V1

---

## Step 2

Await Approval

Human reviews

- Scenes
- Shots
- Durations

---

## Step 3

Resolve Assets

Search

- Local
- Public Domain
- Stock
- AI

---

## Step 4

Generate Media

Generate only missing assets.

---

## Step 5

Render

Generate final MP4.

---

# Events

Examples

```
ProjectCreated

TimelineGenerated

TimelineApproved

AssetsResolved

MediaGenerated

RenderStarted

RenderCompleted

WorkflowCompleted

WorkflowFailed
```

---

# Retry Policy

Retryable

- API timeout
- Rate limits
- Temporary failures

Do Not Retry

- Invalid Script
- Invalid Timeline
- User Cancellation

---

# Progress

Each workflow reports

- Current Step
- Percentage
- Current Task
- Estimated Time

---

# Future

Future versions may support

- Parallel workers
- Distributed queues
- Scheduled execution

---

# Summary

The Workflow Engine coordinates execution while keeping planning and business logic separate.