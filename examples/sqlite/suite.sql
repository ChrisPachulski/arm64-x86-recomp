.headers on
.mode box
SELECT sqlite_version() AS version, sqlite_source_id() IS NOT NULL AS ok;
CREATE TABLE t(id INTEGER PRIMARY KEY, grp TEXT, val REAL, note TEXT);
WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM c WHERE i<200000)
INSERT INTO t SELECT i, 'g'||(i%7), (i*7919)%10007/3.0, printf('row %d says %x', i, i*31) FROM c;
CREATE INDEX t_grp ON t(grp, val);
SELECT grp, count(*) AS n, round(avg(val),4) AS avg, round(sum(val),2) AS total, min(note) AS first FROM t GROUP BY grp ORDER BY grp;
SELECT id, grp, val, rank() OVER (PARTITION BY grp ORDER BY val DESC) AS r,
       round(sum(val) OVER (ORDER BY id ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),3) AS run3
  FROM t WHERE id BETWEEN 1000 AND 1012;
SELECT json_group_array(json_object('id',id,'v',val)) AS j FROM (SELECT id, val FROM t ORDER BY val DESC, id LIMIT 4);
SELECT json_extract('{"a":[1,2,{"b":"deep"}]}', '$.a[2].b') AS deep, json_valid('{bad') AS valid;
SELECT round(sqrt(2),12) AS s, round(sin(pi()/6),12) AS sn, round(exp(1),12) AS e, round(ln(10),12) AS l, 1e308*10 AS inf, 7/2, 7.0/2, -7%3, 0x7fffffffffffffff+0 AS big;
SELECT printf('%.20g|%e|%5.2f|%-8s|%08x|%q', 1.0/3, 123456.789, 3.14159, 'left', 48879, 'it''s') AS fmt;
CREATE VIRTUAL TABLE docs USING fts5(body);
INSERT INTO docs(body) SELECT note FROM t WHERE id % 1000 = 0;
INSERT INTO docs(body) VALUES ('static recompilation of arm64 programs'), ('rosetta in reverse for intel macs');
SELECT rowid, body, round(bm25(docs),6) AS score FROM docs WHERE docs MATCH 'arm64 OR intel' ORDER BY score;
CREATE VIRTUAL TABLE box USING rtree(id, minx, maxx, miny, maxy);
INSERT INTO box SELECT id, val, val+1, id%100, id%100+1 FROM t WHERE id<=5000;
SELECT count(*) AS hits FROM box WHERE minx>100 AND maxx<200 AND miny>10 AND maxy<20;
SELECT upper('mixed Case ÄÖü') AS u, length('naïve'), unicode('é'), hex(zeroblob(3)), quote(x'deadbeef'), typeof(1.5), char(72,105);
SELECT group_concat(name, ',') AS tables FROM (SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name);
WITH RECURSIVE fib(a,b,n) AS (SELECT 0,1,0 UNION ALL SELECT b,a+b,n+1 FROM fib WHERE n<90) SELECT max(a) AS fib90 FROM fib;
SELECT count(*) AS n, total(val) AS t FROM t WHERE note LIKE '%ff%' AND grp GLOB 'g[135]';
PRAGMA integrity_check;
