# Data Model

**Version:** 1.0

---

# Purpose

Defines the persistent storage model.

---

# Project

```
id

name

status

created_at

updated_at
```

---

# Script

```
id

project_id

content

language

version
```

---

# Timeline

```
id

project_id

version

duration

status
```

---

# Scene

```
id

timeline_id

title

summary

duration

order
```

---

# Shot

```
id

scene_id

intent

prompt

camera

duration

transition
```

---

# Asset Plan

```
id

shot_id

strategy

query

preferred_type

fallback
```

---

# Asset

```
id

project_id

provider

type

path

license

confidence
```

---

# Generated Clip

```
id

shot_id

provider

prompt

duration

path
```

---

# Render

```
id

project_id

status

path

duration

resolution
```

---

# Workflow

```
id

project_id

state

progress

current_step
```

---

# Relationships

```
Project

├── Script

├── Timeline

│      ├── Scene

│      │      ├── Shot

│      │      │      ├── AssetPlan

│      │      │      └── Clip

│

├── Assets

└── Render
```

---

# Storage

Version 1

- PostgreSQL
- Local Filesystem
- Redis Cache

Future

- Object Storage
- Distributed Cache
- Vector Database