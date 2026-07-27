#!/usr/bin/env python3
"""
Monsterland Farming Bot - Multi-account passive income farmer
Author: zabuton-ai as a SUPERAGENT
Date: 2026-07-27

Features:
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

# Vitals thresholds (use item if below)
VITALS_THRESHOLD = {
    "food": 30.0,
    "hygiene": 30.0,
    "energy": 20.0
}

# Sleep threshold (sleep if energy below this)
SLEEP_THRESHOLD = 10.0

# Level up config (min LUMIS surplus before level up)
LEVELUP_MIN_LUMIS = 5000

# Item to vital mapping
ITEM_VITAL_MAP = {
    "magic_apple": "food",
    "magic_towel": "hygiene", 
    "wizard_coffee": "energy"
}

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
    
    # 2. Wake up if sleeping (with coffee check)
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
    
    # 3. Use items if vitals low
    for item, vital_type in ITEM_VITAL_MAP.items():
        current_vital = vitals.get(vital_type, 100)
        item_count = inventory.get(item, 0)
        
        if current_vital < VITALS_THRESHOLD.get(vital_type, 30) and item_count > 0:
            r = curl_request("POST", "/api/vitals", init_data, {
                "monsterId": monster_id,
                "itemId": item,
                "action": "use_inventory"
            })
            if "_error" not in r and r.get("success"):
                results["actions"].append(f"used_{item}")
                results["xp"] += r.get("xpGained", 0)
                results["lumis"] = r.get("newLumis", results["lumis"])
                inventory[item] = item_count - 1
            else:
                err = r.get("_error") or r.get("error") or "unknown"
                if "no coffee" not in err.lower():
                    results["errors"].append(f"{item}: {err[:30]}")
    
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
    lines.append("Monsterland - Farming Cycle")
    lines.append("-" * 38)
    
    total_lumis = 0
    ok_count = 0
    
    for r in results_list:
        name = r.get("name", "unknown")[:12].ljust(12)
        lumis = r.get("lumis", 0)
        total_lumis += lumis
        
        if r.get("ok"):
            ok_count += 1
            actions = ", ".join(r.get("actions", []))[:20]
            lines.append(f"{name} {lumis:>8}  {actions}")
        else:
            errors = r.get("errors", ["unknown"])
            lines.append(f"{name} {'FAIL':>8}  {errors[0][:20]}")
    
    lines.append("-" * 38)
    lines.append(f"{'Accounts':12} {len(results_list):>8}")
    lines.append(f"{'OK':12} {ok_count:>8}")
    lines.append(f"{'Total LUMIS':12} {total_lumis:>8}")
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
