from google.cloud import bigquery
import functions_framework
import json

PROJECT = "shield-your-body"
DATASET = "gsc_export"
FQN = f"`{PROJECT}.{DATASET}.keyword_ownership_summary`"

@functions_framework.http
def hello_http(request):
    """
    Cloud Run function to query BigQuery for SEO keyword ownership.
    Modes:
      - latest (default): show most recent snapshot
      - trend: compare latest two snapshots
    """
    try:
        req = request.get_json(silent=True) or {}
        mode = str(req.get("mode", "latest")).strip().lower()
        client = bigquery.Client(project=PROJECT)

        # -----------------------------------------------------------
        # TREND MODE — compare latest vs previous snapshot
        # -----------------------------------------------------------
        if mode == "trend":
            sql = f"""
            WITH latest AS (
              SELECT *
              FROM {FQN}
              WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {FQN})
            ),
            previous AS (
              SELECT *
              FROM {FQN}
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
        # LATEST MODE — show most recent snapshot only
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

        # Run query
        job = client.query(sql)
        rows = [dict(r) for r in job.result()]

        return (
            json.dumps({
                "status": "ok",
                "mode": mode,
                "row_count": len(rows),
                "rows": rows
            }),
            200,
            {"Content-Type": "application/json"}
        )

    except Exception as e:
        return (
            json.dumps({"status": "error", "message": str(e)}),
            500,
            {"Content-Type": "application/json"}
        )