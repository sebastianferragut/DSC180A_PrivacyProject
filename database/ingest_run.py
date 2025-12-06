import json
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "privacyindex")

driver = GraphDatabase.driver(URI, auth=AUTH)

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def ingest_run(run):
    with driver.session() as session:
        session.execute_write(_tx_ingest_run, run)

def _tx_ingest_run(tx, run):
    site = run["site"]
    ts_iso = run["ts_iso"]
    platform = site.split(".")[0]

    # -------------------------
    # PLATFORM + RUN
    # -------------------------
    tx.run(
        """
        MERGE (p:Platform {name: $platform})
        MERGE (r:Run {site: $site, ts_iso: $ts})
        MERGE (p)-[:HAS_RUN]->(r)
        SET r.total_runtime_sec = $runtime,
            r.model_calls = $model_calls
        """,
        platform=platform,
        site=site,
        ts=ts_iso,
        runtime=run["metrics"]["total_runtime_sec"],
        model_calls=run["model_calls"],
    )

    # -------------------------
    # VISITED PAGES
    # -------------------------
    for url in run["state"]["visited_urls"]:
        tx.run(
            """
            MERGE (page:Page {url: $url})
            WITH page
            MATCH (r:Run {site: $site, ts_iso: $ts})
            MERGE (r)-[:VISITED_PAGE]->(page)
            """,
            url=url,
            site=site,
            ts=ts_iso
        )

    # -------------------------
    # SECTIONS
    # -------------------------
    for sec in run["sections"]:
        tx.run(
            """
            MERGE (s:Section {name: $name, url: $url})
            SET s.evidence_fullpage = $fullpage
            WITH s
            MATCH (r:Run {site: $site, ts_iso: $ts})
            MERGE (r)-[:HAS_SECTION]->(s)
            """,
            name=sec["name"],
            url=sec["url"],
            fullpage=sec.get("evidence_fullpage"),
            site=site,
            ts=ts_iso
        )
    # -------------------------
    # SETTINGS (future classifier output)
    # -------------------------
    for sec in run.get("sections", []):
        for item in sec.get("items", []):
            tx.run(
                """
                MATCH (s:Section {name: $sec_name, url: $sec_url})
                MERGE (set:Setting {name: $name, platform: $platform})
                SET set.category = $category,
                    set.current_value = $value,
                    set.options = $options
                MERGE (set)-[:BELONGS_TO_SECTION]->(s)
                """,
                sec_name=sec["name"],
                sec_url=sec["url"],
                name=item["name"],
                category=item.get("category"),
                value=item.get("current_value"),
                options=item.get("options"),
                platform=run["site"].split(".")[0],
            )

    # -------------------------
    # CLICKS
    # -------------------------
    for action in run["actions"]:
        if action["kind"] != "batch_click":
            continue

        sel = action["selector"]

        tx.run(
            """
            MERGE (c:Click {
                ts: $ts,
                selector_type: $stype,
                selector_text: $stext
            })
            WITH c
            MATCH (r:Run {site: $site, ts_iso: $ts_iso})
            MERGE (r)-[:HAS_CLICK]->(c)
            WITH c
            MERGE (to:Page {url: $to_url})
            MERGE (c)-[:TO_PAGE]->(to)
            """,
            ts=action["ts"],
            stype=sel["type"],
            stext=sel["selector"],
            site=site,
            ts_iso=ts_iso,
            to_url=action["url"]
        )

if __name__ == "__main__":
    files = [
        "json_data/facebook.json",
        "json_data/linkedin.json",
        "json_data/zoom.json"
    ]

    for f in files:
        print(f"Ingesting {f} ...")
        data = load_json(f)
        ingest_run(data)

    driver.close()