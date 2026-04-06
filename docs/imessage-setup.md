# iMessage Integration for Hermes Agent

Connect Hermes Agent to Apple's iMessage via macOS Messages.app using the `imsg` CLI tool.

## Overview

The iMessage integration allows Hermes to:
- **Receive** iMessages from allowed contacts
- **Send** replies via iMessage (or SMS fallback)
- **Maintain sessions** per contact for contextual conversations
- **Run cron jobs** that deliver results to iMessage

**Platform:** macOS only (requires Messages.app)

---

## Prerequisites

### 1. macOS with Messages.app

- You must be signed into iMessage on your Mac
- Messages.app should be functional (can send/receive messages)

### 2. Install imsg CLI

```bash
brew install steipete/tap/imsg
```

Verify installation:
```bash
imsg --version
# Should output: imsg 0.4.0 (or newer)
```

### 3. Grant Permissions

iMessage access requires macOS security permissions:

#### Full Disk Access

1. Open **System Settings** → **Privacy & Security** → **Full Disk Access**
2. Click **+** and add your terminal application:
   - For Terminal.app: `/System/Applications/Utilities/Terminal.app`
   - For iTerm2: `/Applications/iTerm.app`
   - For VS Code terminal: `/Applications/Visual Studio Code.app`
3. Restart your terminal after granting permission

#### Automation Permission

When you first run `imsg`, macOS will prompt for Automation access to Messages.app. Click **OK**.

To manually check/grant:
1. **System Settings** → **Privacy & Security** → **Automation**
2. Find your terminal app and ensure **Messages.app** is checked

### 4. Test imsg Access

```bash
imsg chats --limit 5 --json
```

**Expected output:** JSON array of recent chats

**If you see `permissionDenied`:** Full Disk Access not granted correctly — restart terminal and try again.

---

## Configuration

### Environment Variables

Set these in `~/.hermes/.env`:

```bash
# Enable iMessage platform
IMESSAGE_ENABLED=true

# Allowed contacts (comma-separated phone numbers or Apple ID emails)
# Only messages from these contacts will be processed
IMESSAGE_ALLOWED_USERS=+61412345678,+15551234567,marlon@example.com

# Home channel for cron job delivery and notifications
IMESSAGE_HOME_CHANNEL=+61412345678

# Optional: Poll interval in seconds (default: 2)
# Lower = more responsive but higher CPU usage
IMESSAGE_POLL_INTERVAL=2

# Optional: Allow all contacts (NOT recommended for security)
# IMESSAGE_ALLOW_ALL_USERS=true
```

### Using the Setup Wizard

```bash
hermes gateway setup
```

Select **iMessage (macOS)** from the platform list and follow the prompts.

---

## Usage

### Start the Gateway

```bash
# Run in foreground (for testing)
hermes gateway

# Install as background service (macOS launchd)
hermes gateway install
hermes gateway start
```

### Check Status

```bash
hermes status
```

You should see:
```
◆ Messaging Platforms
  iMessage     ✓ configured (home: +61412345678)
```

### In-Chat Commands

Once running, you can message Hermes via iMessage and use commands:

- `/new` — Start a fresh conversation (reset context)
- `/model` — Show or change the AI model
- `/status` — Show gateway status
- `/set-home` — Set this chat as home channel for notifications

---

## How It Works

### Architecture

```
iMessage ←→ imsg CLI ←→ Hermes Gateway ←→ AI Agent
            ↓
      chat.db (polling)
```

### Inbound Messages

The adapter polls `~/Library/Messages/chat.db` every 2 seconds (configurable) for new messages:
- Filters to only messages from allowed users
- Skips messages sent by Hermes (echo prevention)
- Creates a session per contact for contextual conversations

### Outbound Messages

Sends via `imsg send` command:
```bash
imsg send --to "+61412345678" --text "Your message here"
```

### Echo Prevention

The adapter tracks recently sent messages (within 5 seconds) to avoid responding to its own messages — a common issue with database polling approaches.

---

## Known Issues & Limitations

### 1. Full Disk Access Required

Without FDA, `imsg` cannot read `chat.db` and will fail silently or with `permissionDenied` errors.

**Fix:** Grant FDA to your terminal and restart.

### 2. LaunchAgent/FDA Propagation

If running Hermes Gateway as a launchd service, FDA may not propagate correctly.

**Workaround:** Start the gateway from Terminal.app (which has FDA) rather than as a login item.

### 3. Phone Number vs Email Routing

iMessage can route via phone number OR Apple ID email. The adapter uses the identifier from chat.db, but sending may fail if the recipient prefers a different identifier.

**Workaround:** Use the identifier that appears in your Messages.app chat (check the chat info panel).

### 4. Group Messages

Currently treats all chats as direct messages. Group chat support is limited.

### 5. Media Attachments

Image/media sending is not fully implemented. Text-only for now.

### 6. Typing Indicators

Not supported via imsg CLI.

### 7. SMS Fallback

If a recipient doesn't have iMessage, messages may fail unless you explicitly use `--service sms`.

---

## Troubleshooting

### Messages Not Received

1. Check `IMESSAGE_ALLOWED_USERS` includes the sender's identifier
2. Verify FDA is granted: `imsg chats --limit 1` should work
3. Check gateway logs: `tail -f ~/.hermes/logs/gateway.log`

### Messages Not Sent

1. Test manually: `imsg send --to "+61412345678" --text "test"`
2. Check if recipient identifier is correct (try email vs phone)
3. Verify Messages.app is signed in and working

### High CPU Usage

Reduce polling frequency:
```bash
IMESSAGE_POLL_INTERVAL=5  # Check every 5 seconds instead of 2
```

### "permissionDenied" Errors

1. Remove and re-grant Full Disk Access
2. Restart terminal completely (quit and reopen)
3. Test: `imsg chats --limit 1`

---

## Security Considerations

⚠️ **iMessage has access to your personal messages**

- Always use `IMESSAGE_ALLOWED_USERS` — never `ALLOW_ALL_USERS` for iMessage
- The gateway has terminal access — treat iMessage contacts as trusted users
- Consider using a dedicated Apple ID for Hermes if sharing with others

---

## Advanced Configuration

### Custom Polling Strategy

For lower latency, reduce poll interval (higher CPU):
```bash
IMESSAGE_POLL_INTERVAL=1
```

For battery efficiency, increase interval:
```bash
IMESSAGE_POLL_INTERVAL=5
```

### Session Reset Policy

Configure when conversations reset (lose context) in `~/.hermes/gateway.json`:

```json
{
  "reset_by_platform": {
    "imessage": {
      "mode": "idle",
      "idle_minutes": 120
    }
  }
}
```

### Contact Redaction in Logs

Phone numbers are automatically redacted in logs (e.g., `+61412***4567`).

---

## Files Modified

This integration adds/modifies:

- `gateway/platforms/imessage.py` — New adapter
- `gateway/config.py` — Platform enum + config
- `gateway/run.py` — Adapter factory + auth maps
- `gateway/channel_directory.py` — Session-based discovery
- `toolsets.py` — hermes-imessage toolset
- `tools/send_message_tool.py` — Platform routing
- `cron/scheduler.py` — Cron delivery
- `hermes_cli/status.py` — Status display
- `hermes_cli/gateway.py` — Setup wizard

---

## Future Improvements

Potential enhancements:
- [ ] Group chat support with proper detection
- [ ] Image/media attachment sending
- [ ] Typing indicators (if imsg adds support)
- [ ] Contact name resolution caching
- [ ] WebSocket-based message streaming (if imsg adds RPC mode)
- [ ] End-to-end encryption verification

---

## Support

For issues:
1. Check this documentation first
2. Review gateway logs: `~/.hermes/logs/gateway.log`
3. Test imsg directly: `imsg --help`
4. File an issue on the Hermes Agent GitHub
