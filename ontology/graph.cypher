// Neo4j DDL for the Firmable market graph. Idempotent (IF NOT EXISTS). Applied by the loader.

CREATE CONSTRAINT party_key IF NOT EXISTS FOR (p:Party) REQUIRE p.key IS UNIQUE;
CREATE CONSTRAINT org_abn IF NOT EXISTS FOR (o:Organisation) REQUIRE o.abn IS UNIQUE;
CREATE CONSTRAINT org_acn IF NOT EXISTS FOR (o:Organisation) REQUIRE o.acn IS UNIQUE;
CREATE CONSTRAINT org_lei IF NOT EXISTS FOR (o:Organisation) REQUIRE o.lei IS UNIQUE;
CREATE CONSTRAINT licence_id IF NOT EXISTS FOR (l:Licence) REQUIRE l.licence_id IS UNIQUE;
CREATE CONSTRAINT ban_id IF NOT EXISTS FOR (b:Ban) REQUIRE b.ban_id IS UNIQUE;
CREATE CONSTRAINT name_norm IF NOT EXISTS FOR (n:Name) REQUIRE n.normalised IS UNIQUE;
CREATE CONSTRAINT source_record_key IF NOT EXISTS FOR (s:SourceRecord) REQUIRE s.record_key IS UNIQUE;

CREATE INDEX party_display IF NOT EXISTS FOR (p:Party) ON (p.display_name);
CREATE INDEX org_state_postcode IF NOT EXISTS FOR (o:Organisation) ON (o.state, o.postcode);
CREATE INDEX licence_status_end IF NOT EXISTS FOR (l:Licence) ON (l.status, l.end_date);
CREATE INDEX ban_dates IF NOT EXISTS FOR (b:Ban) ON (b.start_date, b.end_date);
CREATE INDEX source_record_source IF NOT EXISTS FOR (s:SourceRecord) ON (s.source_id);

// Full-text over every name variant: the exact/near-exact candidate generator for `resolve`.
CREATE FULLTEXT INDEX name_text IF NOT EXISTS FOR (n:Name) ON EACH [n.text, n.normalised];
