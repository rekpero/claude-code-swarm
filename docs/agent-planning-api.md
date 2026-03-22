# Agent Planning API

External agents can use the SwarmOps planning API to generate implementation plans for a workspace (repo), refine them, and create GitHub issues — all without a browser session.

## Authentication

All requests require an API key passed as a Bearer token:

```
Authorization: Bearer <your-api-key>
```

Configure one or more keys in `.env`:

```
API_KEYS=your-secret-key-here
```

Multiple keys (comma-separated):

```
API_KEYS=key-for-agent-1,key-for-agent-2
```

---

## Endpoints

### 1. Start a planning session

```
POST /api/planning
```

**Request body:**

```json
{
  "workspace_id": "string",
  "message": "string"
}
```

| Field | Description |
|---|---|
| `workspace_id` | ID of the workspace (repo) to plan for. Get this from `GET /api/workspaces`. |
| `message` | Plain-language description of the feature or bug to plan. |

**Response:**

```json
{
  "session": { ...session object... },
  "messages": [ ...message objects... ]
}
```

The session is created and planning starts immediately in the background. The response returns before planning is complete — poll `GET /api/planning/{id}` to wait for the result.

---

### 2. Poll session status and get the plan

```
GET /api/planning/{session_id}
```

**Response:**

```json
{
  "session": {
    "id": "uuid",
    "workspace_id": "string",
    "title": "string",
    "status": "active",
    "issue_number": null,
    "issue_url": null,
    "created_at": "2026-03-22T10:00:00",
    "updated_at": "2026-03-22T10:00:05"
  },
  "messages": [
    {
      "id": 1,
      "session_id": "uuid",
      "role": "user",
      "content": "Add a dark mode toggle to settings",
      "created_at": "2026-03-22T10:00:00"
    },
    {
      "id": 2,
      "session_id": "uuid",
      "role": "assistant",
      "content": "# Dark Mode Toggle\n\n## Overview\n...",
      "created_at": "2026-03-22T10:00:05"
    }
  ],
  "generating": false
}
```

**Poll until `generating == false`.** Once false, the plan is ready in `messages`.

#### Where the plan lives

The generated plan is the **last message with `role == "assistant"`** in the `messages` array. It is a full markdown document containing the implementation spec.

If `generating == true`, the planner subprocess is still running — the assistant message may be absent or incomplete. Do not read the plan until `generating == false`.

#### Session status values

| Status | Meaning |
|---|---|
| `active` | Session is active. Plan may be generating or already ready — check `generating`. |
| `completed` | A GitHub issue has been successfully created from this plan. |
| `error` | Planning failed. Check the last assistant message for details. |

> **Note:** `status` stays `"active"` after a plan is generated. It only becomes `"completed"` after `POST /api/planning/{id}/create-issue` succeeds. Use `generating == false` (not status) to know when the plan is ready to read.

---

### 3. Get planning progress events (optional)

```
GET /api/planning/{session_id}/events?since=0
```

Returns incremental progress events emitted by the planner while it analyzes the codebase. Useful for streaming progress to a UI. Use `since=<last_event_id>` to page through new events.

**Response:**

```json
{
  "events": [
    {
      "id": 1,
      "session_id": "uuid",
      "event_type": "tool_use",
      "summary": "Reading src/components/Header.jsx",
      "created_at": "2026-03-22T10:00:02"
    }
  ]
}
```

This endpoint is optional — agents that only need the final plan can skip it and just poll `GET /api/planning/{id}`.

---

### 4. Refine the plan (optional)

```
POST /api/planning/{session_id}/messages
```

**Request body:**

```json
{
  "message": "string"
}
```

Sends a follow-up message to refine the plan. The planner re-runs with the full conversation history. After calling this, poll `GET /api/planning/{id}` again until `generating == false` — the new plan will be the last assistant message.

**Response:** Same shape as `POST /api/planning` — `{ session, messages }`.

**Error (409):** Returned if planning is already in progress for this session.

---

### 5. Create a GitHub issue from the plan

```
POST /api/planning/{session_id}/create-issue
```

**Request body (optional):**

```json
{
  "title": "string",
  "message_index": null
}
```

| Field | Description |
|---|---|
| `title` | Issue title. If omitted or empty, an AI-generated title is used. |
| `message_index` | 0-based index of the specific assistant message to use as the issue body. Defaults to the last assistant message. |

**Response:**

```json
{
  "issue_number": 42,
  "issue_url": "https://github.com/owner/repo/issues/42",
  "title": "Add dark mode toggle to settings"
}
```

After this call succeeds, the session `status` becomes `"completed"` and `issue_number` / `issue_url` are set on the session object.

The issue is created with:
- The plan as the issue body (markdown)
- The configured `ISSUE_LABEL` applied (default: `agent`)

Comment `@swarmops start` on the issue to dispatch an agent.

**Errors:**

| Status | Reason |
|---|---|
| `400` | No plan found in session, or invalid `message_index` |
| `409` | Plan generation still in progress, or issue already created |

---

### 6. Cancel planning (optional)

```
POST /api/planning/{session_id}/cancel
```

Cancels an in-progress planning run. Safe to call even if not generating.

**Response:** `{ "ok": true }`

---

### 7. Delete a planning session

```
DELETE /api/planning/{session_id}
```

Deletes the session, all messages, and all events. Cancels any in-progress generation first.

**Response:** `{ "ok": true }`

---

## Typical Agent Workflow

```
1. POST /api/planning
   body: { workspace_id, message }
   → get session_id

2. loop:
     GET /api/planning/{session_id}
     → wait until generating == false

3. (optional) if plan needs refinement:
     POST /api/planning/{session_id}/messages
     body: { message: "focus more on error handling" }
     → go back to step 2

4. POST /api/planning/{session_id}/create-issue
   → get issue_number + issue_url

5. (optional) trigger the agent:
   comment "@swarmops start" on the issue via GitHub API
```

---

## Get Workspace IDs

```
GET /api/workspaces
```

**Response:**

```json
{
  "workspaces": [
    {
      "id": "abc123",
      "name": "my-app",
      "github_repo": "owner/repo",
      "status": "active",
      ...
    }
  ]
}
```

Use the `id` field as `workspace_id` in planning requests.
