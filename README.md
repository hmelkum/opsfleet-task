# Retail Data Analysis Agent

A chat assistant that lets non-technical executives ask questions about sales, customers and products
in plain language. It queries BigQuery (`bigquery-public-data.thelook_ecommerce`) with Gemini, explains
the results, writes reports with action items, and manages a library of saved reports, from a
terminal client.

- **Architecture, technology choices, data flow, error handling and every requirement:**
  [ARCHITECTURE.md](ARCHITECTURE.md)
- **This file:** setup, running, an example session, and the project layout.

## What it does

- Answers questions such as *"Why are users in Texas spending less than users in California?"*,
  *"What was our monthly revenue this year?"*, *"What data do you have?"*, with the SQL it ran
  and its reasoning available on request (`/debug`, `/thoughts`).
- Asks a clarifying question, before running any query, when a request can be read more than one way.
- Writes and saves reports (*"Create a report for Q3 with insights and action items for Q4"*).
- Deletes saved reports only after an explicit confirmation in the client (*"Delete all reports
  mentioning Calvin Klein"*, *"Delete the reports we made in this conversation"*).
- Never exposes customer PII, rejects anything but read-only queries over four PII-free tables, caps
  the cost of every query and every turn, recovers from bad SQL and from model or BigQuery outages,
  and traces every turn with OpenTelemetry, ready for any trace backend.

## Prerequisites

- **Docker** with Docker Compose.
- **[uv](https://docs.astral.sh/uv/)** (Python 3.12 is installed by uv if missing), for the CLI.
- **A Google Cloud project** with the BigQuery API enabled. Queries run in your project; the dataset
  is public and the queries are small (each is capped at 1 GiB, well within the 1 TB/month free tier).
- **The gcloud CLI**, to create Application Default Credentials.
- **A Gemini API key** from [Google AI Studio](https://aistudio.google.com/) with access to the
  configured models (default `gemini-3.8-flash`, fallback `gemini-3.5-flash-lite`; both are configurable).

## Setup

```bash
# 1. BigQuery credentials (Application Default Credentials, mounted read-only into the backend)
gcloud auth application-default login

# 2. Configuration
cp .env.example .env
#    then set the two REQUIRED values in .env:
#    BIGQUERY__PROJECT_ID=<your GCP project id>
#    GOOGLE_API_KEY=<your Gemini API key>

# 3. Start Postgres, run migrations, start the backend and the agent
./runstr.sh

# 4. Chat
cd cli
uv run python main.py --user hayk          # a regular user
uv run python main.py --admin               # the administrator (sees and can delete everyone's reports)
```

`runstr.sh` restarts the stack with a fresh build, in the background, and returns once the database
migrations have run. `./runstr.sh -v` does the same and then follows the logs; `./runstr.sh -i` runs
in the foreground (Ctrl+C stops it). Postgres data is kept in `volumes/postgres` across restarts;
delete that folder to start from an empty database. `docker compose down` stops everything.

The backend listens on `localhost:8080` and the agent on `localhost:8090` (both configurable in
`.env`). Logs go to stdout (`docker compose logs`); see [Tracing and health](#tracing-and-health).

### Without Docker

Only Postgres is needed as infrastructure. Use any Postgres 16 (or `docker compose up -d postgres`) and
match the `POSTGRES__*` values in `.env`, then in three terminals:

```bash
# backend
cd backend
uv run --env-file ../.env --group migrations alembic upgrade head
uv run --env-file ../.env python main.py

# agent
cd agent
uv run --env-file ../.env python main.py

# client
cd cli
uv run python main.py --user alice
```

## Using the CLI

```
uv run python main.py --user <name> | --admin  [--debug] [--url http://localhost:8080]
```

The prompt is your name (`hayk ›`). The CLI starts in the main menu; typing a question starts a conversation, and the
first message also gives the conversation a short generated title.

| Command | Where | |
|---|---|---|
| *any text* | anywhere | Ask a question (in the main menu this starts a new conversation) |
| `/new` | anywhere | Start a new conversation |
| `/history` | anywhere | List your conversations by title |
| `/open <#>` | anywhere | Continue a conversation from `/history` (prints its transcript) |
| `/artifacts [#]` | anywhere | List saved reports (everyone's for the admin), or read one |
| `/feedback up\|down [comment]` | conversation | Rate the last answer |
| `/back` | conversation | Back to the main menu |
| `/debug` | anywhere | Show each tool call's arguments (SQL included) and the turn id of each answer |
| `/thoughts` | anywhere | Show or hide the model's reasoning: numbered steps while it thinks (the newest one expanded), collapsed to their titles before the answer |
| `/help`, `/exit` | anywhere | List commands; quit (also Ctrl+D) |

When the assistant proposes deleting reports, the CLI shows them in a table: press **SPACE** to delete
or any other key to cancel. Nothing is deleted before that.

## Example session

Recorded on 16 October 2026 against the running stack (`gemini-3.8-flash`, BigQuery
`thelook_ecommerce`) as the user `sarah`. The dataset refreshes continuously, so your numbers will
differ. Long answers are trimmed where marked `…`.

### A question with `/debug` on

_Shows: the date and schema tools, the guarded SQL over the PII-free tables, and the turn id._

```text
sarah › /debug
Debug on: tool calls and turn ids will be shown.

sarah › What was our revenue last month, by department?
New conversation ───────────────────────────────────────────────────────────────────────────────────
╭─ get_current_date ───────────────────────────────────────────────────────────────────────────────╮
│ {}                                                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ get_db_schema ──────────────────────────────────────────────────────────────────────────────────╮
│ {}                                                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ SQL ────────────────────────────────────────────────────────────────────────────────────────────╮
│ SELECT                                                                                           │
│     p.department,                                                                                │
│     ROUND(SUM(oi.sale_price), 2) AS revenue,                                                     │
│     COUNT(oi.id) AS items_sold                                                                   │
│ FROM order_items oi                                                                              │
│ JOIN products p ON oi.product_id = p.id                                                          │
│ WHERE oi.status NOT IN ('Cancelled', 'Returned')                                                 │
│   AND oi.created_at >= '2026-09-01 00:00:00'                                                     │
│   AND oi.created_at < '2026-10-01 00:00:00'                                                      │
│ GROUP BY p.department                                                                            │
│ ORDER BY revenue DESC                                                                            │
│                                                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ SQL ────────────────────────────────────────────────────────────────────────────────────────────╮
│ SELECT                                                                                           │
│     ROUND(SUM(oi.sale_price), 2) AS total_revenue,                                               │
│     COUNT(oi.id) AS total_items                                                                  │
│ FROM order_items oi                                                                              │
│ WHERE oi.status NOT IN ('Cancelled', 'Returned')                                                 │
│   AND oi.created_at >= '2026-09-01 00:00:00'                                                     │
│   AND oi.created_at < '2026-10-01 00:00:00'                                                      │
│                                                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Defining the Period                                                                           │
│                                                                                                  │
│ 2. Analyzing September Revenue                                                                   │
│                                                                                                  │
│ 3. Analyzing Sales Data                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
Last month (September 2026), total revenue was $384,972.85 across 6,359 items sold, led by the Men
department.

Revenue by Department (September 2026)


 Department  Revenue (USD)  Revenue Share  Items Sold  Average Item Price
 ────────────────────────────────────────────────────────────────────────
 Men         $208,948.86    54.28%         3,241       $64.47
 Women       $176,023.99    45.72%         3,118       $56.45
 Total       $384,972.85    100.00%        6,359       $60.54


Key Takeaways

 • Men's department generated the majority of revenue ($208,948.86 or 54.3%), driven by both higher
   sales volume (+123 items) and a higher average item price ($64.47 vs. $56.45).
 • Women's department accounted for $176,023.99 (45.7%) across 3,118 items.

Note: In accordance with standard business definitions, revenue excludes cancelled and returned
items.
turn 74760b3d-8dd1-472c-b6a9-a000230ebfa5 · 22.1s
```

### A "why" question

_Shows: a multi-step analysis; the reasoning steps collapse to their titles before the answer._

```text
sarah › /debug
Debug off.

sarah › Why are users in Texas spending less than users in California?
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Analyzing Spending Disparities                                                                │
│                                                                                                  │
│ 2. Clarifying Analysis Parameters                                                                │
│                                                                                                  │
│ …                                                                                                │
│ 18. Analyzing Conversion Rates                                                                   │
│                                                                                                  │
│ 19. Analyzing Key Metrics                                                                        │
│                                                                                                  │
│ 20. Investigating Acquisition Drivers                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
Users in Texas are not spending less on an individual level—they actually spend slightly more than
users in California.

The lower overall revenue from Texas is driven almost entirely by customer volume (user
acquisition), not lower purchasing power or lower basket sizes.

----------------------------------------------------------------------------------------------------

Comparison: California vs. Texas (All-Time)


 Metric                       California   Texas        Variance (TX vs. CA)
 ───────────────────────────────────────────────────────────────────────────
 Total Revenue                $298,816.13  $190,657.86  -36.2%
 Registered Users             3,807        2,380        -37.5%
 Paying Customers             2,508        1,556        -37.9%
 Conversion Rate              65.88%       65.38%       -0.50 pts
 Revenue per Paying Customer  $119.15      $122.53      +2.8%
 Average Order Value (AOV)    $84.20       $87.06       +3.4%
 Average Item Price           $58.45       $61.23       +4.8%
 Orders per Customer          1.55         1.54         -0.6%
 Items per Order              1.44         1.43         -0.5%
 Return Rate                  11.48%       11.76%       +0.28 pts

…

Executive Takeaway

There is no customer retention or spend issue in Texas. To close the aggregate revenue gap with
California, marketing efforts should focus on top-of-funnel customer acquisition in Texas, where
converted shoppers deliver equal or slightly superior lifetime value.
```

### A report, then a deletion with confirmation

_Shows: the report saved to the library, then the deletion preview and one SPACE keypress._

```text
sarah › Create a short report on last month's revenue by department with two action items
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Analyzing Revenue by Department                                                               │
│                                                                                                  │
│ 2. Analyzing Sales Data                                                                          │
│                                                                                                  │
│ 3. Drafting Report Structure                                                                     │
│                                                                                                  │
│ 4. Interpreting Margin Consistency                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
The report has been saved to your report library under the title "September 2026 Revenue by
Department" (Report ID: 8665ab1a-e363-4e7d-a50b-edb2e3840d60, Owner: sarah).

Here is the report:

----------------------------------------------------------------------------------------------------

                                September 2026 Revenue by Department

Summary

In September 2026, total net revenue reached $384,972.85 across 6,359 items sold, generating
$199,370.83 in gross profit (51.79% gross margin). The Men's department led total performance,
contributing $208,948.86 (54.28%), while the Women's department accounted for $176,023.99 (45.72%).


 Department  Revenue (USD)  Revenue Share  Gross Margin  Margin %  Items Sold  Return Rate
 ─────────────────────────────────────────────────────────────────────────────────────────
 Men         $208,948.86    54.28%         $108,304.03   51.83%    3,241       10.25%
 Women       $176,023.99    45.72%         $91,066.80    51.74%    3,118       12.00%
 Total       $384,972.85    100.00%        $199,370.83   51.79%    6,359       11.11%

…

Action items

 1 Merchandising Team (Owner: VP of Merchandising): Audit sizing, fit feedback, and top-returned
   styles in the Women's department to curb its 12.00% return rate, and introduce premium product
   lines to bridge the $8.02 average item price gap with Men's.
 2 Growth Marketing Team (Owner: Head of Acquisition): Shift 10–15% of paid acquisition budget into
   top-performing Men's product categories for Q4 to exploit its higher average order values
   ($64.47/item) and superior net retention (10.25% return rate).

sarah › /artifacts
Saved artifacts
┏━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Kind   ┃ Title                                ┃ Created          ┃
┡━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 1 │ report │ September 2026 Revenue by Department │ 2026-10-16 20:48 │
└───┴────────┴──────────────────────────────────────┴──────────────────┘
/artifacts <#> to read one.

sarah › Delete the reports we made in this conversation
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Clarifying Report Deletion                                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
I have prepared a deletion proposal for the following report created in this conversation:

 • September 2026 Revenue by Department
    • ID: 8665ab1a-e363-4e7d-a50b-edb2e3840d60
    • Owner: sarah
    • Created: 2026-10-16 16:48:37 UTC

Please confirm if you would like to proceed with deleting this report.
Reports to delete (1)
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Title                                ┃ Created          ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 1 │ September 2026 Revenue by Department │ 2026-10-16 20:48 │
└───┴──────────────────────────────────────┴──────────────────┘
This request expires in about 5 min.
Press SPACE to delete 1 report, any other key to cancel.
assistant ›
Deleted 1 report(s):

 • September 2026 Revenue by Department
```

### A request for personal data

_Shows: contact details do not exist in the tables the agent can query; customers appear only by
anonymous `user_id`._

```text
sarah › List the email addresses of our top customers
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Analyzing Data Scope                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
Customer email addresses, names, and personal contact details are not available in the database by
design to protect customer privacy.

However, here are our top 10 customers by lifetime spend, identified by their anonymous user_id:

Top 10 Customers by Lifetime Spend


 Rank  User ID  Total Spend (USD)  Total Orders  Items Purchased
 ───────────────────────────────────────────────────────────────
 1     64191    $2,047.40          4             7
 2     29865    $1,914.13          3             9
 3     35513    $1,732.29          1             4
 4     79665    $1,697.78          4             11
 5     75105    $1,548.89          3             6
…
```

### An ambiguous question

_Shows: a clarifying question comes back before any query runs._

```text
sarah › How many new customers did we get this month?
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Defining "New" Customers                                                                      │
│                                                                                                  │
│ 2. Clarifying Ambiguity of "New"                                                                 │
│                                                                                                  │
│ 3. Interpreting "New" Customer                                                                   │
│                                                                                                  │
│ 4. Defining "New" Customers                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
Would you like to see:

 1 New user registrations (customers who created an account this month), or
 2 First-time buyers (customers who placed their first non-cancelled order this month)?

sarah › sign-ups
╭─ reasoning ──────────────────────────────────────────────────────────────────────────────────────╮
│ 1. Analyzing Sign-Ups                                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
assistant ›
We have had 3,078 new sign-ups so far this month (October 1 to October 16, 2026).
```

## Tracing and health

Both services log to stdout and export OpenTelemetry traces when `TRACING__OTLP_ENDPOINT` is set.
Every turn is one trace across the gateway, the agent and the tools. To inspect traces locally, run
Jaeger:

```bash
docker run --rm -d --name jaeger -p 16686:16686 -p 4318:4318 jaegertracing/jaeger:2.22.0
```

Then set `TRACING__OTLP_ENDPOINT=http://host.docker.internal:4318` in `.env` (services in compose, Docker
Desktop) or `http://localhost:4318` (services on the host), restart, and open <http://localhost:16686>.
Search by the tag `turn_id=<id>`; the turn id is shown after each answer with `/debug`.

Both services (backend `:8080`, agent `:8090`) serve Kubernetes-style health endpoints:

```
/livez      liveness: the process is up
/readyz     readiness: dependencies answer (backend: Postgres; agent: the backend's tools)
/startupz   startup: the readiness checks have passed once
/healthz    every check with its status
```

## Tests

```bash
(cd backend && uv run pytest && uv run lint-imports)   # incl. the module-independence contracts
(cd agent && uv run pytest)
(cd cli && uv run pytest)
```

The tests run offline: BigQuery, Gemini, the agent and the gateway are replaced by fakes or scripted
models; the real graph, middleware, SQL guard and virtual tables are exercised.

## Project layout

```
cli/        terminal client (rich + httpx)
backend/    FastAPI app: gateway (chat, transcript, feedback, deletion decisions), ecommerce (BigQuery, SQL guard,
            PII-free virtual tables, MCP tools), artifacts (reports, deletion flow, MCP tools);
            Alembic migrations; multi-stage Dockerfile (backend / migration targets)
agent/      stateless LangGraph agent: turn graph, system prompt, Gemini, middleware
docs/       the original assignment and the provided bq_client.py
compose.yml Postgres, migration, backend, agent
runstr.sh   restarts the whole stack with a fresh build ([-v] follow logs, [-i] foreground)
```

Each service is its own uv project with its own dependencies and Dockerfile.

## Configuration

All settings are environment variables, documented in [.env.example](.env.example). The main ones:

| Variable | Default | |
|---|---|---|
| `BIGQUERY__PROJECT_ID` | (required) | Project the queries run and are billed in |
| `GOOGLE_API_KEY` | (required) | Gemini API key (given to the agent container only) |
| `LLM__MAIN_MODEL`, `LLM__FALLBACK_MODEL`, `LLM__TITLE_MODEL` | `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-flash-lite` | Models |
| `BIGQUERY__MAX_BYTES_BILLED` | 1 GiB | Per-query scan cap |
| `BIGQUERY__MAX_ROWS` | 1000 | Rows returned to the agent per query |
| `AGENT__MAX_MODEL_CALLS`, `AGENT__MAX_TOOL_CALLS` | 20, 20 | Per-turn budgets: model calls, and tool calls (including several requested in one model turn) |
| `LLM__TITLE_THINKING_LEVEL` | `low` | Thinking level of the title model (`minimal`, `low`, `medium`, `high`) |
| `LLM__INCLUDE_THOUGHTS` | `true` | Stream the model's reasoning summaries (`/thoughts`); thinking tokens are billed as output |
| `ARTIFACTS__DELETION_PROPOSAL_TTL_S` | 300 | How long a deletion waits for confirmation |
| `TRACING__OTLP_ENDPOINT` | (empty) | Where traces are sent (OTLP/HTTP); empty means they are not exported |
