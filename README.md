# Monsterland Farming Bot

Automated farming bot for Monsterland Telegram Mini App. Maintains monster vitals, farms XP via chat, and reports LUMIS balance.

## Features

- **Multi-account support** — Process multiple accounts sequentially
- **Vitals maintenance** — Auto-use items when food/hygiene/energy below threshold
- **Wake from sleep** — Auto-wake monster if sleeping and coffee available
- **Chat XP farming** — Send message for free XP (15-18 XP per message)
- **Zero cost** — Script-only mode, no LLM API calls
- **Cron ready** — Designed for scheduled execution via Hermes cron

## Requirements

- Python 3.8+
- `requests` library (or use curl-based version)

## Setup

1. Clone the repo:
```bash
git clone https://github.com/agnetic-ai/monsterland-bot.git
cd monsterland-bot
```

2. Create accounts config:
```bash
cp accounts.json accounts.local.json
```

3. Edit `accounts.local.json` with your initData:
```json
[
  {
    "name": "your_username",
    "init_data": "user=%7B%22id%22%3A...&hash=..."
  }
]
```

4. Run the bot:
```bash
python3 monsterland_farmer.py
```

## Getting initData

1. Open `https://web.telegram.org/k/` in Chrome
2. Login and open `@monsterland_bot`
3. Launch Mini App
4. F12 → Console → Type: `Telegram.WebApp.initData`
5. Copy the string

### Connection Issues?

If you can't open the Monsterland Bot (Mini App fails to load or the frame
stays blank), you need to bypass the site's `X-Frame-Options` restriction.
Install this Chrome extension:

- [**Ignore X-Frame-Headers**](https://chromewebstore.google.com/detail/ignore-x-frame-headers/gleekbfjekiniecknbkamfmkohkpodhe)

Enable it, reload the Mini App, then grab initData from the Console as above.

> initData expires after ~24 hours. Repeat this process to refresh it whenever
> the bot starts reporting `no monster` / auth failures.

## Bot Flow

```
1. Check monster state (sleeping? vitals?)
2. Wake if sleeping + coffee available
3. Use items if vitals below threshold
4. Chat once for XP
5. Report LUMIS balance
```

## Vitals Thresholds

- Food < 30 → Use magic_apple
- Hygiene < 30 → Use magic_towel
- Energy < 20 → Use wizard_coffee

## Cron Setup (Hermes)

```bash
# Create wrapper script
cat > /root/.hermes/scripts/monsterland-farmer.sh << 'EOF'
#!/bin/bash
cd /opt/monsterland-bot
output=$(python3 monsterland_farmer.py 2>&1)
echo "$output"
exit 0
EOF
chmod +x /root/.hermes/scripts/monsterland-farmer.sh

# Create cron job (every 4 hours)
hermes cron create \
  --name monsterland-farmer \
  --schedule "0 */4 * * *" \
  --script monsterland-farmer.sh \
  --no-agent \
  --deliver telegram:your_chat_id
```

## Output Format

```
Monsterland - Farming Cycle
--------------------------------------
ombengz          2734  
estqimo          2427  
--------------------------------------
Accounts            2
OK                  2
Total LUMIS      5161
--------------------------------------
```

## Security Notes

- `accounts.local.json` contains sensitive initData — **NEVER commit this file**
- initData expires after ~24 hours — refresh when needed
- initData is HMAC-signed by Telegram — cannot be forged

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/user?include=monsters` | GET | Get monster state & inventory |
| `/api/profile` | GET | Get LUMIS balance |
| `/api/sleep` | POST | Wake monster from sleep |
| `/api/vitals` | POST | Feed monster: `use_inventory` (free) or `purchase` (LUMIS) |
| `/api/chat` | POST | Send message for XP |

## Known Limitations

- **Roulette** — Endpoint not yet discovered
- **Daily streak** — Requires shield from ads
- **Ads farming** — Requires valid provider auth
- **Level up** — Manual decision (costs LUMIS)

## License

MIT
