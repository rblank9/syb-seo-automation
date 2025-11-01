from google.cloud import bigquery
import functions_framework
import json
from flask import Response

PROJECT = "shield-your-body"
DATASET = "gsc_export"
TABLE = "keyword_ownership_summary"
FQN = f"`{PROJECT}.{DATASET}.{TABLE}`"
PROC_GENERATE = f"{PROJECT}.{DATASET}.generate_keyword_actions_from_candidates"

@functions_framework.http
def hello_http(request):
    """Cloud Run entrypoint for SYB SEO automation."""
    try:
        import sys
        sys.stdout = sys.__stdout__  # ensure clean stdout
        req = request.get_json(silent=True) or {}
        if not req and request.args:
            req = request.args
        mode = str(req.get("mode", "latest")).strip().lower()
        client = bigquery.Client(project=PROJECT)

        # -----------------------------------------------------------
        # MODE: GENERATE ACTIONS  →  run BigQuery procedure
        # -----------------------------------------------------------
        if mode == "generate_actions":
            job = client.query(f"CALL `{PROC_GENERATE}`();")
            job.result()
            return Response(
                json.dumps({"status": "ok", "message": "Actions generated"}, default=str),
                status=200,
                mimetype="application/json",
            )

        # -----------------------------------------------------------
        # MODE: ACTIONS_SUMMARY → summarize keyword_actions table
        # -----------------------------------------------------------
        if mode == "actions_summary":
            sql = f"""
            SELECT
              COALESCE(status, 'unknown') AS status,
              COALESCE(priority, 'normal') AS priority,
              COUNT(*) AS actions,
              MIN(DATE(created_at)) AS first_created,
              MAX(DATE(created_at)) AS last_created
            FROM `{PROJECT}.{DATASET}.keyword_actions`
            GROUP BY status, priority
            ORDER BY status, priority
            """
            job = client.query(sql)
            rows = [dict(r) for r in job.result()]
            return Response(
                json.dumps({"ok": True, "summary": rows}, default=str),
                status=200,
                mimetype="application/json",
            )

        # -----------------------------------------------------------
        # MODE: METRICS → aggregate action statistics
        # -----------------------------------------------------------
        if mode == "metrics":
            sql = f"""
            WITH base AS (
              SELECT
                COALESCE(status, 'unknown') AS status,
                COALESCE(priority, 'normal') AS priority,
                DATE(created_at) AS created_date
              FROM `{PROJECT}.{DATASET}.keyword_actions`
            ),
            priority_counts AS (
              SELECT priority, COUNT(*) AS count FROM base GROUP BY priority
            )
            SELECT
              (SELECT COUNT(*) FROM base) AS total_actions,
              (SELECT COUNTIF(LOWER(status) = 'completed') FROM base) AS completed,
              (SELECT COUNTIF(LOWER(status) != 'completed') FROM base) AS open,
              (SELECT MIN(created_date) FROM base) AS first_created,
              (SELECT MAX(created_date) FROM base) AS last_created,
              TO_JSON_STRING(ARRAY_AGG(STRUCT(priority, count))) AS avg_per_priority_json
            FROM priority_counts;
            """
            job = client.query(sql)
            rows = [dict(r) for r in job.result()]
            if rows:
                metrics = rows[0]
                # Parse JSON string field into structured list
                if metrics.get("avg_per_priority_json"):
                    try:
                        metrics["avg_per_priority"] = json.loads(metrics["avg_per_priority_json"])
                        del metrics["avg_per_priority_json"]
                    except Exception:
                        metrics["avg_per_priority"] = []
                return Response(
                    json.dumps({"ok": True, "metrics": metrics}, default=str),
                    status=200,
                    mimetype="application/json",
                )
            else:
                return Response(
                    json.dumps({"ok": False, "message": "No data found"}, default=str),
                    status=200,
                    mimetype="application/json",
                )

        # -----------------------------------------------------------
        # MODE: TREND → latest vs previous snapshot
        # -----------------------------------------------------------
        if mode == "trend":
            sql = f"""
            WITH latest AS (
              SELECT * FROM {FQN}
              WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {FQN})
            ),
            previous AS (
              SELECT * FROM {FQN}
              WHERE snapshot_date = (
                SELECT MAX(snapshot_date)
                FROM {FQN}
                WHERE snapshot_date < (SELECT MAX(snapshot_date) FROM {FQN})
              )
            )
            SELECT
              l.query,
              l.ownership_recommendation AS latest_recommendation,
              p.ownership_recommendation AS previous_recommendation,
              l.total_impressions AS latest_impressions,
              p.total_impressions AS previous_impressions,
              SAFE_CAST(l.total_impressions AS INT64)
                - SAFE_CAST(p.total_impressions AS INT64) AS impression_change
            FROM latest l
            LEFT JOIN previous p USING (query)
            ORDER BY ABS(SAFE_CAST(l.total_impressions AS INT64)
                - SAFE_CAST(p.total_impressions AS INT64)) DESC
            LIMIT 100;
            """

        # -----------------------------------------------------------
        # MODE: LATEST → most recent snapshot
        # -----------------------------------------------------------
        else:
            sql = f"""
            WITH latest AS (SELECT MAX(snapshot_date) AS d FROM {FQN})
            SELECT
              query,
              ownership_recommendation,
              total_impressions,
              shop_position,
              wp_position
            FROM {FQN}, latest
            WHERE snapshot_date = latest.d
            ORDER BY total_impressions DESC
            LIMIT 50;
            """

        # Execute query modes
        if mode in ("latest", "trend"):
            job = client.query(sql)
            rows = [dict(r) for r in job.result()]
            return Response(
                json.dumps({
                    "status": "ok",
                    "mode": mode,
                    "row_count": len(rows),
                    "rows": rows,
                }, default=str),
                status=200,
                mimetype="application/json",
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_details = {
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__,
            "trace": traceback.format_exc(),
        }
        cause = getattr(e, "__cause__", None)
        if cause:
            error_details["cause"] = str(cause)
        return Response(
            json.dumps(error_details, default=str),
            status=500,
            mimetype="application/json",
        )
# Flask entrypoint for Cloud Run buildpacks
from flask import Flask, request
app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    try:
        # Support both GET and POST; parse JSON for POST
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            if not data:
                return Response(
                    json.dumps({"ok": False, "error": "Empty JSON payload"}),
                    status=400,
                    mimetype="application/json",
                )
            request.args = data
        return hello_http(request)
    except Exception as e:
        import traceback
        error_details = {
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc(),
        }
        return Response(
            json.dumps(error_details, default=str),
            status=500,
            mimetype="application/json",
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)