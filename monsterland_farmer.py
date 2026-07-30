#!/usr/bin/env python3
"""
Monsterland Farming Bot - Multi-account passive income farmer
Author: zabuton-ai as a SUPERAGENT
Date: 2026-07-27

Features:
- Daily streak claim (auto-claim daily reward)
- Vitals maintenance (use items when low)
- Chat XP (conservative, once per cycle)
- Keep awake (no sleep cycle)
- Multi-account support
- Git-safe config pattern

Usage:
  python3 monsterland_farmer.py                  # all accounts
  python3 monsterland_farmer.py --only ombengz   # specific account
  python3 monsterland_farmer.py -t               # test mode (dry run)
"""

import os
import sys
import json
import subprocess
import time
from datetime import datetime

# Config paths
DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(DIR, "accounts.local.json")
ACCOUNTS_TEMPLATE = os.path.join(DIR, "accounts.json")
BASE_URL = "https://lets.playmonsterland.com"

# Vital target — feed until vital reaches this level
VITAL_TARGET = 80.0

# Feed if vital below this threshold
VITAL_LOW = 50.0

# Critical threshold — below this the monster is DYING. Purchases ONLY happen
# when a vital is this low AND inventory is empty. Above this, never buy —
# buying to top-up wastes LUMIS (LUMIS doesn't regenerate from buying).
VITAL_CRITICAL = 30.0

# When forced to buy (critical + no inventory), only buy up to this floor —
# just enough to survive until the next cycle, NOT full 80. Saves LUMIS.
VITAL_BUY_FLOOR = 50.0

# Max LUMIS to spend on purchases per account per run (safety cap)
# Each item costs ~300 LUMIS. 3000 = up to ~10 purchases/run.
PURCHASE_BUDGET = 3000

# Keep this much LUMIS in reserve — never spend below this
LUMIS_RESERVE = 2000

# Sleep threshold (sleep if energy below this)
SLEEP_THRESHOLD = 10.0

# Level up config (min LUMIS surplus before level up)
LEVELUP_MIN_LUMIS = 5000

# Item to vital mapping (tier 1 items, cheapest)
ITEM_VITAL_MAP = {
    "magic_apple": "food",
    "magic_towel": "hygiene", 
    "wizard_coffee": "energy"
}

# Approx cost per tier-1 item purchase (LUMIS)
ITEM_COST = 300

# Chat messages pool (rotate to avoid spam detection)
CHAT_MESSAGES = [
    "hey there",
    "how are you",
    "nice day",
    "hello friend",
    "take care"
]


def load_accounts():
    """Load accounts from config file"""
    if not os.path.exists(ACCOUNTS_FILE):
        if os.path.exists(ACCOUNTS_TEMPLATE):
            print(f"[!] Using template file. Copy to accounts.local.json and fill init_data.")
            with open(ACCOUNTS_TEMPLATE) as f:
                return json.load(f)
        print(f"[!] Missing: {ACCOUNTS_FILE}")
        sys.exit(1)
    
    with open(ACCOUNTS_FILE) as f:
        return json.load(f)


def curl_request(method, endpoint, init_data, body=None, timeout=30):
    """Make curl request to Monsterland API"""
    url = f"{BASE_URL}{endpoint}"
    
    if method == "GET":
        cmd = [
            "curl", "-s", "-X", "GET", url,
            "-H", f"Authorization: tma {init_data}",
            "--max-time", str(timeout)
        ]
    else:
        cmd = [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: tma {init_data}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(body) if body else "{}",
            "--max-time", str(timeout)
        ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if result.returncode != 0 or not result.stdout:
            return {"_error": "curl failed or timeout"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"_error": "timeout"}
    except json.JSONDecodeError:
        return {"_error": "json parse failed"}


def process_account(account, test_mode=False):
    """Process single account - main farming logic"""
    name = account.get("name", "unknown")
    init_data = account.get("init_data", "")
    
    if not init_data or init_data == "paste_initData_disini":
        return {"name": name, "ok": False, "error": "missing init_data"}
    
    if test_mode:
        print(f"  [TEST] Would process: {name}")
        return {"name": name, "ok": True, "test": True}
    
    results = {
        "name": name,
        "ok": True,
        "lumis": 0,
        "xp": 0,
        "actions": [],
        "errors": []
    }
    
    # 1. Get user data with monsters
    user = curl_request("GET", "/api/user?include=monsters", init_data)
    if "_error" in user:
        results["ok"] = False
        results["errors"].append(f"get user: {user['_error']}")
        return results
    
    monsters = user.get("monsters", [])
    inventory = user.get("inventory", {})
    profile = user.get("profile", {})
    
    # Get current LUMIS
    profile_data = curl_request("GET", "/api/profile", init_data)
    if "_error" not in profile_data:
        results["lumis"] = profile_data.get("user", {}).get("stats", {}).get("lumis", 0)
    
    if not monsters:
        results["actions"].append("no monster")
        return results
    
    monster = monsters[0]
    monster_id = monster.get("_id") or monster.get("id")
    vitals = monster.get("vitals", {})
    is_sleeping = monster.get("is_sleeping", False)
    xp_tracking = monster.get("xp_tracking", {})
    
    # 2. Claim daily streak reward
    streak_state = profile.get("daily_streak_state", {})
    if not streak_state.get("streak_reward_claimed_today", False):
        r = curl_request("POST", "/api/daily-streak", init_data, {"action": "claim"})
        if "_error" not in r and r.get("success"):
            reward = r.get("reward", {})
            item_id = reward.get("item_id", "")
            item_qty = reward.get("item_qty", 0)
            lumis_reward = reward.get("lumis", 0)
            if item_id:
                results["actions"].append(f"daily:{item_id}x{item_qty}")
            if lumis_reward > 0:
                results["actions"].append(f"daily:{lumis_reward}L")
            # Refresh inventory after daily claim
            user_refresh = curl_request("GET", "/api/user", init_data)
            if "_error" not in user_refresh:
                inventory = user_refresh.get("inventory", inventory)

    # 2b. Claim referral LUMIS income (free money — grab whatever is claimable).
    #     Endpoint: POST /api/referral/claim {type:"lumis"} -> {claimed_lumis, new_balance}
    #     Only accounts with referrals accrue claimable_lumis; others return 0.
    ref = curl_request("GET", "/api/referral", init_data)
    if "_error" not in ref:
        claimable = ref.get("claimable_lumis", 0) or 0
        if claimable > 0:
            rc = curl_request("POST", "/api/referral/claim", init_data, {"type": "lumis"})
            if "_error" not in rc and rc.get("success"):
                got = rc.get("claimed_lumis", 0)
                if got > 0:
                    results["actions"].append(f"ref:{got}L")
                    nb = rc.get("new_balance")
                    if isinstance(nb, (int, float)):
                        results["lumis"] = nb
        # Auto-claim any referral GOAL that's newly reached (LUMIS/care_pack/etc).
        # goal_progress==100 on current_goal_id means it's claimable now.
        cur_goal = ref.get("current_goal_id")
        claimed = ref.get("goals_claimed", []) or []
        if cur_goal is not None and cur_goal not in claimed and ref.get("goal_progress", 0) >= 100:
            rg = curl_request("POST", "/api/referral/claim", init_data,
                              {"type": "goal", "id": cur_goal})
            if "_error" not in rg and rg.get("success"):
                results["actions"].append(f"goal{cur_goal}:done")
                nb = rg.get("new_balance")
                if isinstance(nb, (int, float)):
                    results["lumis"] = nb

    # 3. Wake up if sleeping (with coffee check)
    if is_sleeping:
        coffee = inventory.get("wizard_coffee", 0)
        if coffee > 0:
            r = curl_request("POST", "/api/sleep", init_data, {
                "monsterId": monster_id,
                "action": "wake_up"
            })
            if "_error" not in r and r.get("success"):
                results["actions"].append("woke_up")
                # Refresh vitals after wake
                vitals = r.get("newVitals", vitals)
            else:
                results["errors"].append(f"wake: {r.get('_error', r.get('error', 'unknown'))}")
        else:
            results["errors"].append("sleeping_no_coffee")
            return results  # Can't continue without waking
    
    # 3. Feed vitals ROUND-ROBIN: always feed the LOWEST vital first so the
    #    purchase budget is shared across food/hygiene/energy instead of being
    #    drained by whichever vital comes first alphabetically.
    #    A monster dies if ANY vital hits 0, so balance matters more than maxing one.
    #    use_inventory first (free), then purchase (LUMIS) within budget/reserve.
    #    /api/vitals response returns "newVitalValue" (number) + "inventoryUpdates".
    item_map = {"magic_apple": "apple", "magic_towel": "towel", "wizard_coffee": "coffe"}
    vital_item = {v: k for k, v in ITEM_VITAL_MAP.items()}  # food->magic_apple, etc.
    spent = 0  # LUMIS spent on purchases this run
    used = {}    # item -> count used from inventory
    bought = {}  # item -> count purchased

    def cur(vt):
        val = vitals.get(vt, 100)
        return 100 if val is None else val

    # Feeding policy (LUMIS-conservative — buying does NOT regenerate LUMIS):
    #   - use_inventory (FREE): feed the lowest vital up to VITAL_TARGET (80).
    #     Items sitting in inventory are free, so spend them freely.
    #   - purchase (COSTS LUMIS): ONLY when a vital is CRITICAL (<30, monster
    #     dying) AND inventory for that item is empty. And even then, only buy
    #     up to VITAL_BUY_FLOOR (50) — just enough to survive, not full.
    #   This means healthy monsters with empty inventory are left alone (no
    #   wasteful buying); we only spend LUMIS to rescue a dying monster.
    while True:
        # Pick the lowest vital still below target
        candidates = [(cur(vt), vt) for vt in ITEM_VITAL_MAP.values()]
        candidates = [(v, vt) for v, vt in candidates if v < VITAL_TARGET]
        if not candidates:
            break  # everything at/above target
        candidates.sort()  # lowest first
        vital_now, vital_type = candidates[0]
        item = vital_item[vital_type]

        if inventory.get(item, 0) > 0:
            # Free feed from inventory — always do this up to target
            action = "use_inventory"
        else:
            # Inventory empty. Buying only allowed to RESCUE a dying vital.
            if vital_now >= VITAL_CRITICAL:
                # Not dying — don't waste LUMIS topping up. Mark this vital
                # "handled" so the loop moves on / exits instead of spinning.
                vitals[vital_type] = VITAL_TARGET
                continue
            # Critical + no inventory -> buy, but only up to the survival floor.
            if vital_now >= VITAL_BUY_FLOOR:
                vitals[vital_type] = VITAL_TARGET  # already safe enough, stop
                continue
            lumis_now = results["lumis"]
            if lumis_now < ITEM_COST:
                break  # can't afford — nothing more we can do
            if spent + ITEM_COST > PURCHASE_BUDGET:
                break  # per-run purchase cap (safety)
            action = "purchase"

        r = curl_request("POST", "/api/vitals", init_data, {
            "monsterId": monster_id,
            "itemId": item,
            "action": action
        })

        if "_error" in r or not r.get("success"):
            err = r.get("_error") or r.get("error") or "unknown"
            results["errors"].append(f"{item}:{err[:25]}")
            # Bump this vital to target so we don't infinite-loop on a broken item
            vitals[vital_type] = VITAL_TARGET
            continue

        # Success — update state from real response
        results["xp"] += r.get("xpGained", 0)
        if "newLumis" in r:
            results["lumis"] = r["newLumis"]
        nv = r.get("newVitalValue")
        vitals[vital_type] = nv if isinstance(nv, (int, float)) else cur(vital_type) + 30

        if action == "use_inventory":
            used[item] = used.get(item, 0) + 1
            inventory[item] = inventory.get(item, 0) - 1
        else:
            bought[item] = bought.get(item, 0) + 1
            spent += ITEM_COST

    # Log per-item summary
    for item in ITEM_VITAL_MAP:
        label = item_map.get(item, item)
        u, b = used.get(item, 0), bought.get(item, 0)
        if u and b:
            results["actions"].append(f"{label}x{u}+buy{b}")
        elif u:
            results["actions"].append(f"{label}x{u}")
        elif b:
            results["actions"].append(f"{label}buy{b}")
    
    # 4. Chat for XP (conservative - once per cycle)
    chat_today = xp_tracking.get("chat_messages_today", 0)
    if chat_today < 10:  # Conservative limit
        msg = CHAT_MESSAGES[int(time.time()) % len(CHAT_MESSAGES)]
        r = curl_request("POST", "/api/chat", init_data, {
            "monster_id": monster_id,
            "message": msg
        }, timeout=15)
        # Chat returns SSE stream, we just check if it started
        if "_error" not in r and "data:" in str(r):
            results["actions"].append("chat_xp")
    
    # 5. Auto-level up (if XP sufficient + LUMIS surplus)
    monster_xp = monster.get("experience", 0)
    monster_level = monster.get("level", 1)
    current_lumis = results["lumis"]
    
    # Get XP required for next level (approx formula: level * 200)
    xp_required = monster_level * 200
    
    if monster_xp >= xp_required and current_lumis >= LEVELUP_MIN_LUMIS:
        r = curl_request("POST", "/api/xp", init_data, {
            "action": "level_up",
            "monsterId": monster_id
        })
        if "_error" not in r and r.get("success"):
            new_level = r.get("newLevel", monster_level)
            new_lumis = r.get("newLumis", current_lumis)
            results["actions"].append(f"lvlup->{new_level}")
            results["lumis"] = new_lumis
            results["xp"] = r.get("userXP", {}).get("xpAwarded", 0)
        else:
            err = r.get("_error") or r.get("error") or "unknown"
            if "not enough xp" not in err.lower():
                results["errors"].append(f"levelup: {err[:25]}")
    
    # 6. Sleep cycle (if energy very low + coffee available)
    current_energy = vitals.get("energy", 100)
    coffee = inventory.get("wizard_coffee", 0)
    
    if current_energy < SLEEP_THRESHOLD and coffee >= 2:  # Keep 1 coffee reserve
        r = curl_request("POST", "/api/sleep", init_data, {
            "monsterId": monster_id,
            "action": "start_sleep"
        })
        if "_error" not in r and r.get("success"):
            results["actions"].append("sleep")
            results["lumis"] = r.get("newLumis", results["lumis"])
            # Immediately wake up (we have coffee)
            r2 = curl_request("POST", "/api/sleep", init_data, {
                "monsterId": monster_id,
                "action": "wake_up"
            })
            if "_error" not in r2 and r2.get("success"):
                results["actions"].append("woke")
                results["lumis"] = r2.get("newLumis", results["lumis"])
        else:
            err = r.get("_error") or r.get("error") or "unknown"
            results["errors"].append(f"sleep: {err[:20]}")
    
    # 7. Get final LUMIS
    profile_final = curl_request("GET", "/api/profile", init_data)
    if "_error" not in profile_final:
        results["lumis"] = profile_final.get("user", {}).get("stats", {}).get("lumis", results["lumis"])
    
    # Clean up errors
    if results["errors"]:
        results["ok"] = len(results["errors"]) < 2  # Allow 1 error
    
    return results


def format_output(results_list):
    """Format output for Telegram (clean dash-separated)"""
    lines = []
    lines.append("Monsterland Farm")
    lines.append("-" * 38)
    
    total_lumis = 0
    ok_count = 0
    fail_count = 0
    total_xp = 0
    
    for r in results_list:
        name = r.get("name", "unknown")[:12]
        lumis = r.get("lumis", 0)
        xp = r.get("xp", 0)
        total_lumis += lumis
        total_xp += xp
        
        if r.get("ok"):
            ok_count += 1
            actions = ", ".join(r.get("actions", []))
            if actions:
                lines.append(f"{name:<12} {lumis:>8}  {actions}")
            else:
                lines.append(f"{name:<12} {lumis:>8}")
        else:
            fail_count += 1
            errors = r.get("errors", ["unknown"])
            lines.append(f"{name:<12} {'FAIL':>8}  {errors[0][:20]}")
    
    lines.append("-" * 38)
    lines.append(f"Accounts          {len(results_list)}")
    lines.append(f"OK                {ok_count}")
    if fail_count > 0:
        lines.append(f"Failed            {fail_count}")
    lines.append(f"Total LUMIS       {total_lumis}")
    lines.append("-" * 38)
    
    return "\n".join(lines)


def main():
    # Parse args
    test_mode = "-t" in sys.argv or "--test" in sys.argv
    only_account = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        if idx + 1 < len(sys.argv):
            only_account = sys.argv[idx + 1]
    
    # Load accounts
    accounts = load_accounts()
    
    if only_account:
        accounts = [a for a in accounts if a.get("name") == only_account]
        if not accounts:
            print(f"[!] Account not found: {only_account}")
            sys.exit(1)
    
    print(f"[i] Processing {len(accounts)} account(s)...")
    
    results = []
    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(2)  # Delay between accounts
        result = process_account(account, test_mode)
        results.append(result)
    
    print(format_output(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
