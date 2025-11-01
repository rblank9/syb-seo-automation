SYB SEO Automation

Automated SEO diagnostics and action planning for ShieldYourBody.com across Shopify and WordPress using Google Search Console exports in BigQuery. Served via Cloud Run.

Overview
	•	Cloud Run service: syb-seo-automation
	•	Region: europe-west1
	•	Runtime: Python 3.11 (Buildpacks + Functions Framework)
	•	Entrypoint: hello_http
	•	Public URL: https://syb-seo-automation-31032723003.europe-west1.run.app
	•	Data source: BigQuery project shield-your-body
	•	Core table: gsc_export.keyword_ownership_summary
	•	Aux tables: gsc_export.keyword_actions
	•	View: gsc_export.v_keyword_action_candidates
	•	Procedure: gsc_export.generate_keyword_actions_from_candidates()

What it does
	•	mode=latest — returns the most recent keyword ownership snapshot
	•	mode=trend — returns deltas versus the previous snapshot
	•	mode=generate_actions — calls the stored procedure to insert new action items into keyword_actions

Quick start

Call the API

# Latest snapshot
curl -sS "https://syb-seo-automation-31032723003.europe-west1.run.app?mode=latest"

# Trend
curl -sS "https://syb-seo-automation-31032723003.europe-west1.run.app?mode=trend"

# Generate actions
curl -sS "https://syb-seo-automation-31032723003.europe-west1.run.app?mode=generate_actions"

JSON response shape
	•	mode=latest:

{
  "status": "ok",
  "mode": "latest",
  "row_count": 50,
  "rows": [
    {
      "query": "emf protection",
      "ownership_recommendation": "Shopify owns|WordPress owns|Hybrid (keep both)",
      "total_impressions": 13,
      "shop_position": 45.5,
      "wp_position": 61.5
    }
  ]
}

	•	mode=trend:

{
  "status": "ok",
  "mode": "trend",
  "row_count": 100,
  "rows": [
    {
      "query": "emf meter",
      "latest_recommendation": "Shopify owns",
      "previous_recommendation": "WordPress owns",
      "latest_impressions": 13,
      "previous_impressions": 10,
      "impression_change": 3
    }
  ]
}

	•	mode=generate_actions:

{ "status": "ok", "message": "Actions generated" }

Repo layout

.
├── main.py                # Cloud Run handler + SQL
├── requirements.txt       # functions-framework, bigquery client
└── README.md

requirements.txt

functions-framework==3.*
google-cloud-bigquery==3.*

Local development

Prereqs: Python 3.11.

git clone https://github.com/rblank9/syb-seo-automation.git
cd syb-seo-automation
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run locally
functions-framework --target=hello_http --port=8080

# Test
curl -sS "http://localhost:8080?mode=latest"

Local BigQuery calls need ADC (Application Default Credentials). If you want to run queries locally:

gcloud auth application-default login

Deployment

The service is configured for Continuously deploy from a repository in Cloud Run.

Console path:
	•	Cloud Run → Create service → Continuously deploy from a repository
	•	Repo: rblank9/syb-seo-automation, branch main
	•	Build:
	•	Builder: Python 3 (Buildpack)
	•	Source dir: /
	•	Container arguments: --target=hello_http
	•	Port: 8080
	•	Authentication: Allow public access
	•	Service account: 31032723003-compute@developer.gserviceaccount.com

A new commit to main triggers Cloud Build and deploys a new revision.

BigQuery objects

Project: shield-your-body
	•	Core table: `gsc_export.keyword_ownership_summary`
	•	Expected columns: snapshot_date DATE, query STRING, ownership_recommendation STRING, total_impressions INT64, shop_position FLOAT64, wp_position FLOAT64, plus any others you maintain.
	•	Actions table: `gsc_export.keyword_actions`
	•	Suggested columns: keyword STRING, action_type STRING, priority STRING, status STRING, assigned_to STRING, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), created_date DATE AS (DATE(created_at)) STORED
	•	Partition: created_date
	•	Cluster: keyword, action_type
	•	Candidates view: `gsc_export.v_keyword_action_candidates` → supplies new recommended actions
	•	Procedure:

CALL `shield-your-body.gsc_export.generate_keyword_actions_from_candidates`();



SQL used by the service
	•	Latest:

WITH latest AS (SELECT MAX(snapshot_date) AS d FROM `shield-your-body.gsc_export.keyword_ownership_summary`)
SELECT
  query,
  ownership_recommendation,
  total_impressions,
  shop_position,
  wp_position
FROM `shield-your-body.gsc_export.keyword_ownership_summary`, latest
WHERE snapshot_date = latest.d
ORDER BY total_impressions DESC
LIMIT 50;

	•	Trend:

WITH latest AS (
  SELECT * FROM `shield-your-body.gsc_export.keyword_ownership_summary`
  WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM `shield-your-body.gsc_export.keyword_ownership_summary`)
),
previous AS (
  SELECT * FROM `shield-your-body.gsc_export.keyword_ownership_summary`
  WHERE snapshot_date = (
    SELECT MAX(snapshot_date) FROM `shield-your-body.gsc_export.keyword_ownership_summary`
    WHERE snapshot_date < (SELECT MAX(snapshot_date) FROM `shield-your-body.gsc_export.keyword_ownership_summary`)
  )
)
SELECT
  l.query,
  l.ownership_recommendation AS latest_recommendation,
  p.ownership_recommendation AS previous_recommendation,
  l.total_impressions AS latest_impressions,
  p.total_impressions AS previous_impressions,
  SAFE_CAST(l.total_impressions AS INT64) - SAFE_CAST(p.total_impressions AS INT64) AS impression_change
FROM latest l
LEFT JOIN previous p USING (query)
ORDER BY ABS(SAFE_CAST(l.total_impressions AS INT64) - SAFE_CAST(p.total_impressions AS INT64)) DESC
LIMIT 100;

	•	Generate actions:

CALL `shield-your-body.gsc_export.generate_keyword_actions_from_candidates`();

IAM

Runtime service account: 31032723003-compute@developer.gserviceaccount.com

Grant:
	•	BigQuery Job User (project)
	•	BigQuery Data Viewer (dataset or project)
	•	BigQuery Data Editor on dataset gsc_export (dataset-level preferred)

Scheduler and Slack (optional)

Scheduler (weekly digest)

Cloud Scheduler → Create job:
	•	Frequency: 0 13 * * MON
	•	Target: HTTP
	•	URL: https://syb-seo-automation-31032723003.europe-west1.run.app?mode=latest
	•	Auth: OIDC
	•	Service account: a scheduler SA with Cloud Run Invoker

Slack webhook
	•	Store SLACK_WEBHOOK_URL in Secret Manager
	•	In main.py, add a format branch format=slack and POST a simple blocks payload

Data hygiene
	•	Partition keyword_actions by created_date and cluster by keyword, action_type
	•	Inside the procedure, prevent duplicates with MERGE on (keyword, action_type, DATE(created_at))
	•	Normalize timestamps to UTC

Example MERGE:

MERGE `shield-your-body.gsc_export.keyword_actions` T
USING src S
ON T.keyword = S.keyword
AND T.action_type = S.action_type
AND DATE(T.created_at) = DATE(S.created_at)
WHEN NOT MATCHED THEN
  INSERT (keyword, action_type, priority, status, assigned_to)
  VALUES (S.keyword, S.action_type, S.priority, 'open', S.assigned_to);

Troubleshooting
	1.	HTTP 503 from Cloud Run
	•	Usually no process listening on $PORT. With buildpacks, ensure:
	•	requirements.txt exists at repo root
	•	functions-framework is in requirements
	•	main.py imports functions_framework
	•	A Flask app is defined or you pass --target=hello_http and the handler exists
	2.	DefaultCredentialsError locally
	•	Run gcloud auth application-default login
	3.	BigQuery Forbidden when calling procedure
	•	Add BigQuery Data Editor on dataset gsc_export to the runtime service account
	4.	GPT says “external service unavailable” but curl works
	•	The GPT-side endpoint URL is stale. Use https://syb-seo-automation-31032723003.europe-west1.run.app

Versioning and change control
	•	Branch: main auto-deploys to production via Cloud Run
	•	Commit messages should be imperative and scoped, e.g.:
	•	feat(actions): weekly digest formatter
	•	fix(trend): guard for missing previous snapshot
	•	chore(deploy): bump functions-framework 3.x

License

Proprietary. Copyright © Shield Your Body.
