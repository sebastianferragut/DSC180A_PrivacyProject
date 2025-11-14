from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "privacyindex"))

def get_sections(platform):
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Platform {name: $platform})-[:HAS_RUN]->(r)-[:HAS_SECTION]->(s)
            RETURN s.name AS name, s.url AS url
            """,
            platform=platform,
        )
        return [dict(record) for record in result]

if __name__ == "__main__":
    print(get_sections("accountscenter"))