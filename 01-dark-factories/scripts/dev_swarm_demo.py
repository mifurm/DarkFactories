"""Dev helper: run the bearing-wear narrative headlessly and print the ledger story."""
import time
from nightshift.plant.core import PlantCore

c = PlantCore("KAT-1", seed=5, swarm=True, sim_first="surrogate")
c.run(180)
c.plant.inject_fault("bearing_wear", asset="CNC-04", ttf_h=10)
for _ in range(60):
    c.run(10)
    v = c.pdm.models["CNC-04"].view
    if v.get("alert") and v.get("rul_min"):
        print("t", c.plant.t, "alert health_est", v.get("health_est"), "rul", v.get("rul_min"), v.get("signature"))
        break
print("true health", round(c.plant.assets["CNC-04"].health, 3))
c.run(120)
print(c.supervisor.stats)
for e in c.ledger.query(limit=40, desc=False)["items"][-16:]:
    print(e["sim_time"][11:], e["kind"], e["agent"], "|", e["summary"][:120])
print("WOs", [(w.asset, w.start_t, w.status) for w in c.plant.work_orders.values()])
print("inbox", [(i.id, i.title) for i in c.inbox.pending()])
print("CNC-04", c.plant.assets["CNC-04"].state, "failures", c.plant.assets["CNC-04"].failures, "verify", c.ledger.verify()["ok"])
t0 = time.perf_counter(); c.run(480); print("480 ticks swarm", round(time.perf_counter() - t0, 2), "s")
