"""Choice-task design for the consumer benchmark (Study 2).

Each respondent gets n_tasks screens (default 8 = each category once) with
3 listings each. Within a category every
listing shows the same spec table; the manipulated attributes are:

  brand_type   industrial | d2c (fictitious names with back-stories)
               real_high | real_low (real brands, no back-story)
  affect       0/1  lifestyle scene + emotional tagline + "As seen on TV"
  claim        none | unverifiable | verifiable (licence / report number)
  price_mult   0.85 / 0.95 / 1.05 / 1.15 x reference price
  rating       3.9 / 4.2 / 4.5
  warranty     category-specific levels

Within a task the three claim levels and three rating levels each appear
once (balanced), three of the four brand types appear, prices are drawn
without replacement, and affect always varies. Fictitious names are
randomly paired with the industrial or D2C back-story per respondent, so
name effects are not confounded with the back-story.

The same function generates stimuli for the AI-agent study (Study 1):
pass a fixed seed and the agents see exactly the same choice sets.
"""
import hashlib
import json
import random
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config" / "stimuli.json"

BRAND_TYPES = ["industrial", "d2c", "real_high", "real_low"]
CLAIMS = ["none", "unverifiable", "verifiable"]
N_ALTS = 3


def load_stimuli(path=CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def price_point(ref, mult):
    """Indian-retail style price ending in 9 (or 4 for cheap items)."""
    p = ref * mult
    step = 5 if ref < 200 else 10
    return int(round(p / step) * step - 1)


def cert_id(cat, brand):
    h = int(hashlib.sha256(f"{cat['id']}|{brand}".encode()).hexdigest(), 16)
    if cat["cert"]["type"] == "BIS":
        return f"CM/L-{7000000 + h % 2999999}"
    return f"TR-2026-{10000 + h % 89999}"


def claim_text(cat, claim):
    if claim == "none":
        return ""
    if cat["cert"]["type"] == "BIS":
        if claim == "verifiable":
            return f"BIS certified ({cat['cert']['standard']})"
        return "Certified premium quality & safety"
    if claim == "verifiable":
        return "Tested at an NABL-accredited lab"
    return "Tested for premium quality & performance"


def _order_categories(cat_ids, n_tasks, rng):
    """Every category once, the rest repeated, no category twice in a row."""
    base = list(cat_ids)
    extra_needed = n_tasks - len(base)
    while extra_needed > 0:
        take = min(extra_needed, len(cat_ids))
        base += rng.sample(cat_ids, take)
        extra_needed -= take
    base = base[:n_tasks]
    for _ in range(5000):
        rng.shuffle(base)
        if all(base[i] != base[i + 1] for i in range(len(base) - 1)):
            return base
    return base


def generate_design(stimuli, seed, n_tasks=8):
    rng = random.Random(seed)
    cats = {c["id"]: c for c in stimuli["categories"]}
    mults = stimuli["price_multipliers"]
    ratings = stimuli["ratings"]

    # fictitious name <-> back-story pairing, fixed within respondent
    fict = {}
    for cid, c in cats.items():
        names = list(c["fictitious"])
        rng.shuffle(names)
        fict[cid] = {"industrial": names[0], "d2c": names[1]}

    order = _order_categories(list(cats), n_tasks, rng)
    tasks = []
    for t, cid in enumerate(order):
        c = cats[cid]
        types = rng.sample(BRAND_TYPES, N_ALTS)
        claims = rng.sample(CLAIMS, N_ALTS)
        rts = rng.sample(ratings, N_ALTS)
        pm = rng.sample(mults, N_ALTS)
        affect = [0, 1, rng.randint(0, 1)]
        rng.shuffle(affect)
        alts = []
        for k in range(N_ALTS):
            bt = types[k]
            if bt in ("industrial", "d2c"):
                brand = fict[cid][bt]
                story = c["industrial_story"] if bt == "industrial" else c["d2c_story"]
            else:
                brand = c[bt]
                story = ""
            alts.append({
                "pos": k,
                "brand": brand,
                "brand_type": bt,
                "fictitious": int(bt in ("industrial", "d2c")),
                "backstory": story,
                "affect": affect[k],
                "tagline": rng.choice(c["affect"]["taglines"]) if affect[k] else "",
                "claim": claims[k],
                "claim_text": claim_text(c, claims[k]),
                "cert_id": cert_id(c, brand) if claims[k] == "verifiable" else "",
                "price_mult": pm[k],
                "price": price_point(c["ref_price"], pm[k]),
                "rating": rts[k],
                "reviews": rng.randint(1200, 3800),
                "warranty_years": rng.choice(c["warranty_years"]),
            })
        tasks.append({
            "task_index": t,
            "category": cid,
            "alts": alts,
        })

    return {"seed": seed, "tasks": tasks, "fictitious_map": fict}


def public_categories(stimuli):
    """Category info the browser needs to render listings."""
    out = {}
    for c in stimuli["categories"]:
        out[c["id"]] = {k: c[k] for k in (
            "id", "name", "need", "title", "icon", "spec", "cert", "affect")}
        out[c["id"]]["warranty_label"] = c.get("warranty_label", "Warranty")
    return out

