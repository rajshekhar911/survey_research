# Shopping Choices Study: survey website

This is the website for the human product-choice survey in "When the customer is a machine".

A participant goes through three steps:
1. **Consent:** one tick box.
2. **8 product screens:** each screen shows 3 listings. One tap picks a listing and moves to the next screen.
3. **Thank you:** a completion code and a short debrief.

It takes about 2–3 minutes. There are no other questions and no reward.

It needs only **Python 3.9+**, with nothing to install. Data is stored in one SQLite file.

```
survey_app/
  server.py            backend (API, admin dashboard, data exports)
  design.py            builds each person's 8 choice screens (also used for agent stimuli)
  config/settings.json study text, contact, ethics no., number of screens, panel redirect
  config/stimuli.json  8 product categories, brands, back-stories, claims, prices
  static/              participant site, admin dashboard, stimulus viewer
  tests/test_e2e.py    end-to-end tests
  data/                survey.db is created here (never commit or share it)
```

## Run it

```bash
cd survey_app
python3 -m unittest discover -s tests          # should print OK
ADMIN_PASSWORD='pick-a-long-password' python3 server.py --port 8000
```

* **Participants** go to `http://localhost:8000/`.
  * For a panel, use `/?pid=<panel_id>&src=<panel_name>`.
  * The same `pid` cannot answer twice.
* **Researchers** go to `http://localhost:8000/admin` (user `admin`). It shows live counts, choice shares, the downloads and the stimulus viewer.

## Before launch

1. **Fill the `[bracketed]` fields** in `config/settings.json`. The consent page shows them.
2. **Panel redirect:** if you use a panel, set `completion_redirect`. It can contain `{code}` and `{pid}`.
3. **Check `config/stimuli.json`:**
   * reference prices against today's market;
   * each fictitious brand name against the trademark registry.
4. **Ethics committee:** show them the consent page and the debrief. The debrief discloses the made-up brands and the hypothetical prices, ratings and certificates.
5. **Number of screens:** `n_tasks` sets it. 8 shows each category once. Values up to 16 repeat categories, giving more data per person but a longer survey.

## Choice screens (design.py)

Every listing on a screen shows the **same specification table**. What varies:

| Attribute | Levels | Within each screen |
|---|---|---|
| Brand type | fictitious *industrial* back-story · fictitious *D2C* back-story · real high-footprint · real low-footprint | 3 of the 4 |
| Affect layer | off / on (lifestyle scene + emotional tagline + "As seen on TV") | always varies |
| Claim | none · unverifiable · verifiable (BIS licence / NABL report no. + Verify button) | each level once |
| Price | 0.85 / 0.95 / 1.05 / 1.15 × reference | 3 different |
| Rating | 3.9 / 4.2 / 4.5 | each level once |
| Warranty | category-specific | random |

* **Position** of the listings on screen is randomised.
* **Name and back-story pairing** of the fictitious brands is randomised per person, so name effects are not confounded with pedigree.

## Data (admin → Downloads)

| File | Contents |
|---|---|
| `choices_long.csv` | One row per listing shown, with all attributes, `chosen` (0/1), response time and `quality_pass`. Ready for a conditional / HB logit, using `log_price_rel` as the price term. |
| `respondents.csv` | One row per person: status, timing, device size and flags. |
| `events.csv` | Verify-button use (with time spent) and tab switches. |
| `choice_sets.json` | The exact choice sets and choices. Give these to the AI agents so they make the same choices people made. |

**Flags:**
* `speeder`: finished faster than `min_seconds` (default 40 s). Only this flag fails `quality_pass`.
* `position_straightline`: always picked the same position. Shown for information only.

## Agent study stimuli

`/admin/stimulus?seed=123&t=0&buttons=0` renders screen 0 of the design for seed 123,
exactly as people see it. `?r=<respondent_id>&t=3` renders a real participant's screen 3.

From Python:

```python
import design
d = design.generate_design(design.load_stimuli(), seed=123)
```

## Put it online

1. Run the server on a small VPS.
2. Put HTTPS in front of it with Caddy (`reverse_proxy 127.0.0.1:8000`).
3. Start the server with `--trust-proxy`.
4. Back up `data/survey.db` daily.

For a quick pilot without a server, run `cloudflared tunnel --url http://localhost:8000` on your own machine.

Security:
* Participants get a random session token; nothing personal is collected.
* IP addresses are stored only as a salted hash, for spotting duplicates.
* The admin pages use basic auth, so always serve them over HTTPS.
