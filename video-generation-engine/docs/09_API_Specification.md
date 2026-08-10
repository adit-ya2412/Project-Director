# API Specification

**Version:** 1.0

---

# Purpose

Defines the REST API exposed by the backend.

Base URL

```
/api/v1
```

---

# Projects

## Create Project

POST

```
/projects
```

---

## List Projects

GET

```
/projects
```

---

## Get Project

GET

```
/projects/{id}
```

---

## Delete Project

DELETE

```
/projects/{id}
```

---

# Script

## Upload Script

POST

```
/projects/{id}/script
```

---

## Get Script

GET

```
/projects/{id}/script
```

---

# Timeline

## Generate Timeline

POST

```
/projects/{id}/timeline
```

---

## Get Timeline

GET

```
/projects/{id}/timeline
```

---

## Approve Timeline

POST

```
/projects/{id}/timeline/approve
```

---

# Assets

## Resolve Assets

POST

```
/projects/{id}/assets/resolve
```

---

## List Assets

GET

```
/projects/{id}/assets
```

---

# Generation

## Generate Missing Media

POST

```
/projects/{id}/generate
```

---

# Rendering

## Render Video

POST

```
/projects/{id}/render
```

---

## Download Video

GET

```
/projects/{id}/video
```

---

# Workflow

## Status

GET

```
/projects/{id}/status
```

---

## Progress

GET

```
/projects/{id}/progress
```

---

# Health

GET

```
/health
```

---

# Future APIs

- Authentication
- Users
- Teams
- Providers
- Templates
- Publishing