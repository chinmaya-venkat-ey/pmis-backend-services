import json, sys
v2 = json.load(open(sys.argv[1])); pid = sys.argv[2]
def q(s): return "'" + str(s).replace("'", "''") + "'"
rows = []
for r in v2["rate_fix"]:
    rows.append(f"({q(r['activityName'])}, {q(r['designation'])}, {r['monthlyRate']}, {r['computedCost']})")
vals = ",\n  ".join(rows)
print(f"""BEGIN;
UPDATE project.activity_planned_resources apr
SET monthly_rate = v.rate, computed_cost = v.cost
FROM (VALUES
  {vals}
) AS v(aname, desig, rate, cost),
     project.activities a
WHERE a.name = v.aname AND a.project_id = {q(pid)}
  AND apr.activity_id = a.id AND apr.designation = v.desig;
COMMIT;""")
